import os
import io
import asyncio
import re
import json
import logging
import base64
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse, FileResponse
import json as json_lib
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import httpx
from PIL import Image
import fal_client
import replicate
from bs4 import BeautifulSoup

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('costs.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
cost_logger = logging.getLogger('costs')
cost_logger.setLevel(logging.INFO)

app = FastAPI(title="Background Remover API")

# Статические файлы (CSS, JS)
app.mount("/static", StaticFiles(directory="."), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище токенов Яндекс Диска
yandex_tokens = set()

# Модели обработки
async def process_removebg(image_bytes: bytes, api_key: str) -> bytes:
    """Remove.bg API"""
    async with httpx.AsyncClient() as client:
        files = {"image_file": ("image.jpg", image_bytes, "image/jpeg")}
        data = {"size": "auto"}
        headers = {"X-Api-Key": api_key}
        
        response = await client.post(
            "https://api.remove.bg/v1.0/removebg",
            files=files,
            data=data,
            headers=headers,
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Remove.bg API error: {response.text}")
        
        return response.content

async def process_clipdrop(image_bytes: bytes, api_key: str) -> bytes:
    """Clipdrop API"""
    async with httpx.AsyncClient() as client:
        files = {"image_file": ("image.jpg", image_bytes, "image/jpeg")}
        headers = {"x-api-key": api_key}
        
        response = await client.post(
            "https://clipdrop-api.co/remove-background/v1",
            files=files,
            headers=headers,
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Clipdrop API error: {response.text}")
        
        return response.content

async def process_replicate(image_bytes: bytes, api_key: str, prompt: Optional[str] = None) -> bytes:
    """Replicate API с fallback на три модели: bria/remove-background (primary), 851-labs/background-remover (fallback 1), lucataco/remove-bg (fallback 2)"""
    # Используем REPLICATE_API_KEY из .env если не передан ключ
    if not api_key:
        api_key = os.getenv("REPLICATE_API_KEY", "")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="Replicate API key not provided")
    
    # Проверяем доступные методы (упрощенное логирование для production)
    try:
        logging.info("Initializing Replicate client...")
        if hasattr(replicate, 'Client'):
            logging.info("replicate.Client available")
        if hasattr(replicate, 'run'):
            logging.info("replicate.run available")
        if hasattr(replicate, 'files'):
            logging.info("replicate.files available")
    except Exception as debug_error:
        logging.warning(f"Error during replicate module check: {str(debug_error)}")
    
    # Устанавливаем API токен для replicate
    # Согласно документации, replicate.run() использует REPLICATE_API_TOKEN из env
    os.environ["REPLICATE_API_TOKEN"] = api_key
    
    # Согласно документации Replicate, можно передать file object напрямую в replicate.run()
    # replicate.run() автоматически загрузит файл, если это необходимо
    logging.info(f"Replicate: Preparing image file (size: {len(image_bytes)} bytes)")
    
    # Список моделей для попытки (primary и fallback)
    models = [
        {
            "name": "bria/remove-background",
            "full_id": "bria/remove-background"
        },
        {
            "name": "851-labs/background-remover",
            "full_id": "851-labs/background-remover:9b8eab58c339c82a5da60a688a164abfa0e4f7a9b80ab7f3cf6d7a8d3e9f2a0f"
        },
        {
            "name": "lucataco/remove-bg",
            "full_id": "lucataco/remove-bg:95fcc2a26d3899cd6c2691c900465aaeff466285a65c14638cc5f36f34befaf1"
        }
    ]
    
    # Пробуем каждый модель, используя первый успешный
    last_error = None
    for idx, model_info in enumerate(models):
        try:
            logging.info(f"Trying Replicate model {idx + 1}/{len(models)}: {model_info['name']}")
            
            # Создаем новый BytesIO для каждой попытки (так как он может быть использован)
            file_obj = io.BytesIO(image_bytes)
            file_obj.name = "image.jpg"
            
            # Подготавливаем input для модели
            # Согласно документации Replicate, можно передать file object напрямую
            # bria/remove-background может принимать file object или URL
            # 851-labs/background-remover и lucataco/remove-bg тоже принимают file objects
            if model_info['name'] == "bria/remove-background":
                # bria/remove-background принимает image как file object или URL
                model_input = {
                    "image": file_obj
                }
            else:
                # Inne modele принимают image, format i background_type
                model_input = {
                    "image": file_obj,
                    "format": "png",
                    "background_type": "rgba"  # прозрачный фон
                }
            
            # Используем replicate.run() - согласно документации Replicate
            # replicate.run() синхронный, используем asyncio.to_thread() для async
            # Согласно документации, replicate.run() может принимать file objects напрямую
            logging.info(f"Running model {model_info['name']} with file object (size: {len(image_bytes)} bytes)")
            output = await asyncio.to_thread(
                replicate.run,
                model_info['full_id'],
                input=model_input
            )
            
            logging.info(f"Replicate model {model_info['name']} succeeded, output type: {type(output)}")
            logging.info(f"Replicate output value (first 200 chars): {str(output)[:200] if output else 'None'}")
            if isinstance(output, list):
                logging.info(f"Output is a list with {len(output)} items")
                for idx, item in enumerate(output[:3]):  # Log first 3 items
                    logging.info(f"  Output[{idx}]: {type(item)}, value: {str(item)[:100]}")
            
            # output может быть FileOutput объект (с методом .read()) или список FileOutput
            # Согласно документации Replicate v1.0.0+, replicate.run() возвращает FileOutput объекты
            result_bytes = None
            
            if hasattr(output, 'read'):
                # Если это FileOutput объект (replicate v1.0.0+)
                logging.info("Output is FileOutput object, using .read() method")
                result_bytes = output.read()
            elif isinstance(output, list) and len(output) > 0:
                # Если это список FileOutput объектов, берем первый
                logging.info(f"Output is a list with {len(output)} items, using first item")
                first_item = output[0]
                if hasattr(first_item, 'read'):
                    result_bytes = first_item.read()
                elif isinstance(first_item, str):
                    # Если это URL строка
                    output_url = first_item
                else:
                    output_url = str(first_item)
            elif isinstance(output, str):
                # Если это строка URL
                output_url = output
            elif hasattr(output, 'url'):
                # Если это объект с URL
                output_url = output.url
            else:
                # Пробуем преобразовать в строку (может быть URL)
                output_url = str(output) if output else None
            
            # Если result_bytes уже получен через .read(), возвращаем его
            if result_bytes:
                logging.info(f"Replicate processing completed successfully using model: {model_info['name']}")
                return result_bytes
            
            # Если есть URL, скачиваем результат
            if output_url:
                logging.info(f"Downloading result from URL: {output_url[:100]}...")
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.get(output_url, timeout=60.0, follow_redirects=True)
                    if response.status_code != 200:
                        raise HTTPException(status_code=500, detail=f"Failed to download Replicate result: {response.status_code}")
                    result_bytes = response.content
                    logging.info(f"Replicate processing completed successfully using model: {model_info['name']}")
                    return result_bytes
            
            # Если ничего не сработало
            raise HTTPException(status_code=500, detail=f"Unexpected Replicate output format: {type(output)}, value: {str(output)[:200]}")
            
        except HTTPException:
            # HTTPException пробрасываем дальше без fallback
            raise
        except Exception as e:
            # Сохраняем ошибку и пробуем следующий модель
            last_error = e
            logging.warning(f"Replicate model {model_info['name']} failed: {str(e)}, trying next model...")
            continue
    
    # Если все модели не удались, выбрасываем последнюю ошибку
    if last_error:
        logging.error(f"All Replicate models failed. Last error: {str(last_error)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"All Replicate models failed. Last error: {str(last_error)}")
    else:
        raise HTTPException(status_code=500, detail="All Replicate models failed without error details")
        
        # Используем replicate.run с новым моделью и URL изображения
        # replicate.run() синхронный, но możemy użyć asyncio.to_thread() dla async
async def process_fal(image_bytes: bytes, api_key: str, prompt: Optional[str] = None) -> bytes:
    """FAL через fal-client используя fal-ai/imageutils/rembg"""
    import base64
    
    # Используем FAL_KEY из .env если не передан ключ, иначе устанавливаем переданный
    # FAL_KEY скрыт в переменных окружения (Railway variables или .env)
    if not api_key:
        api_key = os.getenv("FAL_KEY", "")
    if api_key:
        os.environ["FAL_KEY"] = api_key
    
    try:
        # FAL требует upload файла в их storage и получения URL
        # fal_client.upload() принимает bytes напрямую, не BytesIO
        # Upload файла в FAL storage и получаем URL (synchronous, не async)
        image_url = fal_client.upload(image_bytes, content_type="image/jpeg")
        
        # Проверяем, что URL получен
        if not image_url:
            raise HTTPException(status_code=500, detail="FAL: Failed to upload image, no URL returned")
        
        logging.info(f"FAL image uploaded, URL: {image_url[:100]}...")
        
        # Подготавливаем аргументы для fal-ai/imageutils/rembg
        arguments = {
            "image_url": image_url
        }
        
        # Используем fal-client для асинхронной обработки
        # FAL_KEY должен быть установлен в окружении (загружается из .env или Railway variables)
        handler = await fal_client.submit_async(
            "fal-ai/imageutils/rembg",
            arguments=arguments,
        )
        
        # Ждем завершения и логируем события
        async for event in handler.iter_events(with_logs=True):
            # Можно логировать события если нужно
            if hasattr(event, 'type'):
                logging.info(f"FAL event: {event.type}")
        
        result = await handler.get()
        
        # Логируем результат для отладки
        logging.info(f"FAL result type: {type(result)}, content: {str(result)[:200] if result else 'None'}")
        
        # Получаем URL результата
        # FAL возвращает {"image": {"url": "...", ...}} или {"image": "url_string"}
        result_url = None
        if isinstance(result, dict):
            if "image" in result:
                image_data = result["image"]
                # Если image это объект с url
                if isinstance(image_data, dict) and "url" in image_data:
                    result_url = image_data["url"]
                # Если image это строка (URL)
                elif isinstance(image_data, str):
                    result_url = image_data
            elif "output" in result:
                output_data = result["output"]
                if isinstance(output_data, dict) and "url" in output_data:
                    result_url = output_data["url"]
                elif isinstance(output_data, str):
                    result_url = output_data
            elif "images" in result and len(result["images"]) > 0:
                first_image = result["images"][0]
                if isinstance(first_image, dict) and "url" in first_image:
                    result_url = first_image["url"]
                elif isinstance(first_image, str):
                    result_url = first_image
        elif isinstance(result, str):
            result_url = result
        
        if not result_url:
            logging.error(f"FAL result structure: {result}")
            raise HTTPException(status_code=500, detail=f"FAL: No image URL in result. Result: {str(result)[:500]}")
        
        # Скачиваем результат
        async with httpx.AsyncClient() as client:
            response = await client.get(result_url, timeout=60.0)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to download FAL result: {response.status_code}")
            return response.content
            
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"FAL processing error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"FAL processing error: {str(e)}")

async def process_fal_object_removal(image_bytes: bytes, api_key: str, prompt: Optional[str] = None) -> bytes:
    """FAL через fal-client используя fal-ai/image-editing/object-removal"""
    
    # Используем FAL_KEY из .env если не передан ключ, иначе устанавливаем переданный
    # FAL_KEY скрыт в переменных окружения (Railway variables или .env)
    if not api_key:
        api_key = os.getenv("FAL_KEY", "")
    if api_key:
        os.environ["FAL_KEY"] = api_key
    
    try:
        # FAL требует upload файла в их storage и получения URL
        # fal_client.upload() принимает bytes напрямую, не BytesIO
        # Upload файла в FAL storage и получаем URL (synchronous, не async)
        image_url = fal_client.upload(image_bytes, content_type="image/jpeg")
        
        # Проверяем, что URL получен
        if not image_url:
            raise HTTPException(status_code=500, detail="FAL: Failed to upload image, no URL returned")
        
        logging.info(f"FAL Object Removal image uploaded, URL: {image_url[:100]}...")
        
        # Подготавливаем аргументы для fal-ai/image-editing/object-removal
        arguments = {
            "image_url": image_url
        }
        
        # Используем fal_client.submit_async() для асинхронной обработки (podobnie jak process_fal)
        # FAL_KEY должен быть установлен в окружении (загружается из .env или Railway variables)
        handler = await fal_client.submit_async(
            "fal-ai/image-editing/object-removal",
            arguments=arguments,
        )
        
        # Ждем завершения и логируем события
        async for event in handler.iter_events(with_logs=True):
            # Можно логировать события если нужно
            if hasattr(event, 'type'):
                logging.info(f"FAL Object Removal event: {event.type}")
            # Логируем сообщения из логов
            if hasattr(event, 'logs') and event.logs:
                for log in event.logs:
                    if isinstance(log, dict) and 'message' in log:
                        logging.info(f"FAL Object Removal log: {log.get('message', '')}")
        
        result = await handler.get()
        
        # Логируем результат для отладки
        logging.info(f"FAL Object Removal result type: {type(result)}, content: {str(result)[:200] if result else 'None'}")
        
        # Получаем URL результата
        # FAL возвращает {"image": {"url": "...", ...}} или {"image": "url_string"}
        result_url = None
        if isinstance(result, dict):
            if "image" in result:
                image_data = result["image"]
                # Если image это объект с url
                if isinstance(image_data, dict) and "url" in image_data:
                    result_url = image_data["url"]
                # Если image это строка (URL)
                elif isinstance(image_data, str):
                    result_url = image_data
            elif "output" in result:
                output_data = result["output"]
                if isinstance(output_data, dict) and "url" in output_data:
                    result_url = output_data["url"]
                elif isinstance(output_data, str):
                    result_url = output_data
            elif "images" in result and len(result["images"]) > 0:
                first_image = result["images"][0]
                if isinstance(first_image, dict) and "url" in first_image:
                    result_url = first_image["url"]
                elif isinstance(first_image, str):
                    result_url = first_image
        elif isinstance(result, str):
            result_url = result
        
        if not result_url:
            logging.error(f"FAL Object Removal result structure: {result}")
            raise HTTPException(status_code=500, detail=f"FAL Object Removal: No image URL in result. Result: {str(result)[:500]}")
        
        # Скачиваем результат
        async with httpx.AsyncClient() as client:
            response = await client.get(result_url, timeout=60.0)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to download FAL Object Removal result: {response.status_code}")
            return response.content
            
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"FAL Object Removal processing error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"FAL Object Removal processing error: {str(e)}")

# Модели
MODELS = {
    "removebg": process_removebg,
    "clipdrop": process_clipdrop,
    "replicate": process_replicate,
    "fal": process_fal,
    "fal_object_removal": process_fal_object_removal
}

def get_api_key(model: str, api_key_from_request: Optional[str] = None) -> str:
    """Получение API ключа из запроса или env"""
    if api_key_from_request:
        return api_key_from_request
    
    env_keys = {
        "removebg": os.getenv("REMOVEBG_API_KEY"),
        "clipdrop": os.getenv("CLIPDROP_API_KEY"),
        "replicate": os.getenv("REPLICATE_API_KEY"),
        "fal": os.getenv("FAL_KEY"),
        "fal_object_removal": os.getenv("FAL_KEY"),  # Использует тот же ключ что и FAL
    }
    
    key = env_keys.get(model) or ""
    
    # Логируем для отладки (только если ключ не найден)
    if not key and model == "replicate":
        logging.debug(f"REPLICATE_API_KEY not found in environment variables")
    
    return key

@app.get("/api/test/replicate-key")
async def test_replicate_key():
    """Тест проверки REPLICATE_API_KEY из переменных окружения"""
    api_key = os.getenv("REPLICATE_API_KEY")
    if api_key:
        # Не возвращаем сам ключ, только информацию о его наличии
        return {
            "status": "ok",
            "key_exists": True,
            "key_length": len(api_key),
            "key_prefix": api_key[:4] + "..." if len(api_key) > 4 else "***"
        }
    else:
        return {
            "status": "error",
            "key_exists": False,
            "message": "REPLICATE_API_KEY not found in environment variables"
        }

@app.get("/")
async def root():
    """Главная страница"""
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "Background Remover API", "status": "running"}

@app.post("/api/process")
async def process_image(
    image: UploadFile = File(...),
    model: str = Form(...),
    apiKey: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None)
):
    """Обработка изображения для удаления фона"""
    if model not in MODELS:
        raise HTTPException(status_code=400, detail="Unknown model")
    
    api_key = get_api_key(model, apiKey)
    if not api_key:
        raise HTTPException(status_code=400, detail="API key not provided")
    
    try:
        image_bytes = await image.read()
        logging.info(f"Processing image with model: {model}, size: {len(image_bytes)} bytes")
        
        # Вызываем соответствующую функцию обработки
        # Все функции принимают (image_bytes, api_key, prompt)
        processed_bytes = await MODELS[model](image_bytes, api_key, prompt)
        
        logging.info(f"Processing completed successfully, result size: {len(processed_bytes)} bytes")
        return Response(
            content=processed_bytes,
            media_type="image/png"
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in /api/process endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/place-on-background")
async def place_on_background(
    processedImage: UploadFile = File(...),
    prompt: Optional[str] = Form(None)
):
    """Размещение обработанного изображения на фоне используя prunaai/p-image-edit"""
    import replicate
    import os
    
    api_key = os.getenv("REPLICATE_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="REPLICATE_API_KEY not found")
    
    try:
        # Загружаем обработанное изображение
        processed_image_bytes = await processedImage.read()
        
        # Путь к файлу фона - пробуем разные пути
        background_paths = [
            "/app/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg",
            os.path.expanduser("~/background_remover/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg"),
            "/app/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpg.pdf",
            os.path.expanduser("~/background_remover/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpg.pdf")
        ]
        
        background_path = None
        for path in background_paths:
            if os.path.exists(path):
                background_path = path
                break
        
        if not os.path.exists(background_path):
            raise HTTPException(status_code=500, detail=f"Background file not found at {background_path}")
        
        # Читаем файл фона
        with open(background_path, 'rb') as f:
            background_image_bytes = f.read()
        
        # Устанавливаем API токен для replicate
        os.environ["REPLICATE_API_TOKEN"] = api_key
        
        # Согласно документации Replicate, можно передать file objects напрямую в replicate.run()
        # Model prunaai/p-image-edit принимает images как список file objects или URL
        # Передаем file objects напрямую - replicate автоматически их обработает
        processed_file_obj = io.BytesIO(processed_image_bytes)
        processed_file_obj.name = "processed.png"
        background_file_obj = io.BytesIO(background_image_bytes)
        background_file_obj.name = "background.jpeg"
        
        logging.info("Preparing images for prunaai/p-image-edit model...")
        
        # Prompt для модели - используем переданный или дефолтный
        default_prompt = """Add the product from @img2 to the image @img1.

The original image @img1 contains a podium without a levitating product; do not remove or replace any existing elements.

The product must levitate directly above the podium, barely touching the podium surface, with a visible contact shadow.

The shadow cast by the product must appear ONLY on the top horizontal surface of the podium.
The shadow must be restricted strictly to the upper flat surface where an object could be placed.
No shadows are allowed on the podium sides, vertical faces, edges, or base.
No shadows from the product are allowed on the background or any other surfaces.

The product must be large, visually dominant, and clearly readable.
The product must not appear small, distant, or miniature.

If the product from @img2 is horizontally oriented or elongated, rotate the product to a vertical orientation to improve composition and perceived size.

The product must be well-lit with hard directional lighting.
Use hard-edged but soft-density shadows.
Shadows must be light, natural, and semi-transparent, with no pure black or crushed shadows.

The product width must match the podium width exactly.
The product must not be wider or narrower than the podium.

The product height must start just above the podium surface and extend upward close to the top edge of the image without being cropped.

Do not allow the product to overlap or cover any text elements or the character located on the right side of the image.

Preserve the original camera angle, style, lighting direction, and color palette.
Do not modify any existing elements except adding the product.

Preserve the original image format, proportions, and horizontal 4:3 aspect ratio (1600×1200 equivalent).
Do not crop or resize the image."""
        
        # Используем переданный prompt или дефолтный
        if not prompt or prompt.strip() == "":
            prompt = default_prompt
        
        # Подготавливаем input для модели
        # Согласно документации, images может быть списком file objects или URL
        # @img1 - это первый image (фон), @img2 - второй image (продукт)
        # Перемещаем указатели файлов в начало для чтения
        background_file_obj.seek(0)
        processed_file_obj.seek(0)
        
        model_input = {
            "images": [background_file_obj, processed_file_obj],  # @img1 - фон, @img2 - продукт
            "prompt": prompt,
            "aspect_ratio": "4:3"  # Сохраняем соотношение сторон как в оригинале
        }
        
        logging.info(f"Running prunaai/p-image-edit model...")
        
        # Запускаем модель
        output = await asyncio.to_thread(
            replicate.run,
            "prunaai/p-image-edit",
            input=model_input
        )
        
        logging.info(f"Model output type: {type(output)}")
        
        # Получаем результат
        result_bytes = None
        if hasattr(output, 'read'):
            result_bytes = output.read()
        elif isinstance(output, str):
            # Если это URL, скачиваем изображение
            async with httpx.AsyncClient() as client:
                response = await client.get(output, timeout=60.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail=f"Failed to download result: {response.status_code}")
                result_bytes = response.content
        elif isinstance(output, list) and len(output) > 0:
            first_item = output[0]
            if hasattr(first_item, 'read'):
                result_bytes = first_item.read()
            elif isinstance(first_item, str):
                async with httpx.AsyncClient() as client:
                    response = await client.get(first_item, timeout=60.0)
                    if response.status_code != 200:
                        raise HTTPException(status_code=500, detail=f"Failed to download result: {response.status_code}")
                    result_bytes = response.content
        
        if not result_bytes:
            raise HTTPException(status_code=500, detail="Failed to get result from model")
        
        logging.info(f"Place on background completed successfully, result size: {len(result_bytes)} bytes")
        
        return Response(
            content=result_bytes,
            media_type="image/png"
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in /api/place-on-background endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/place-template")
async def place_template(
    image: UploadFile = File(...),
    template: str = Form("default"),
    width: int = Form(1200),
    height: int = Form(1200)
):
    """Размещение обработанного изображения на шаблон с настраиваемым размером"""
    try:
        # Загружаем изображение
        image_bytes = await image.read()
        processed_img = Image.open(io.BytesIO(image_bytes))
        
        # Получаем размеры шаблона из параметров
        template_width = max(100, min(5000, width))  # Ограничиваем от 100 до 5000
        template_height = max(100, min(5000, height))  # Ограничиваем от 100 до 5000
        
        # Создаем белый шаблон нужного размера
        template_img = Image.new("RGB", (template_width, template_height), "white")
        
        # Получаем размеры изображения
        img_width, img_height = processed_img.size
        
        # Масштабируем изображение так, чтобы оно поместилось в шаблон с сохранением пропорций
        # Используем меньший масштаб, чтобы изображение полностью поместилось в шаблон
        # Вычисляем масштаб для заполнения по ширине и высоте, выбираем меньший
        scale_width = template_width / img_width
        scale_height = template_height / img_height
        
        # Используем меньший масштаб, чтобы изображение поместилось полностью
        # Это гарантирует, что изображение не будет обрезано, а вокруг будет белое поле
        scale = min(scale_width, scale_height)
        
        # Масштабируем изображение
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        processed_img = processed_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Центрируем изображение на белом фоне
        x = (template_width - new_width) // 2
        y = (template_height - new_height) // 2
        
        # Создаем результат
        result = template_img.copy()
        if processed_img.mode == "RGBA":
            result.paste(processed_img, (x, y), processed_img)
        else:
            result.paste(processed_img, (x, y))
        
        # Сохраняем в bytes
        output = io.BytesIO()
        result.save(output, format="PNG")
        output.seek(0)
        
        return Response(
            content=output.read(),
            media_type="image/png"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Яндекс Диск OAuth
@app.get("/auth/yandex")
async def yandex_auth():
    """Начало OAuth авторизации Яндекс Диска"""
    client_id = os.getenv("YANDEX_DISK_CLIENT_ID")
    # Используем переменную окружения или определяем автоматически
    redirect_uri = os.getenv("YANDEX_DISK_REDIRECT_URI")
    if not redirect_uri:
        # Пытаемся определить URL автоматически из запроса
        from fastapi import Request
        # Для Railway и других платформ лучше использовать переменную окружения
        # В локальной разработке можно использовать localhost
        redirect_uri = "http://localhost:8000/auth/yandex/callback"
    
    auth_url = f"https://oauth.yandex.ru/authorize?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=auth_url)

@app.get("/auth/yandex/callback")
async def yandex_callback(code: Optional[str] = None):
    """OAuth callback Яндекс Диска"""
    if not code:
        return Response(content='<script>window.close();</script>', media_type="text/html")
    
    client_id = os.getenv("YANDEX_DISK_CLIENT_ID")
    client_secret = os.getenv("YANDEX_DISK_CLIENT_SECRET")
    # Используем переменную окружения (обязательно для Railway)
    redirect_uri = os.getenv("YANDEX_DISK_REDIRECT_URI")
    if not redirect_uri:
        # Fallback для локальной разработки
        redirect_uri = "http://localhost:8000/auth/yandex/callback"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth.yandex.ru/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0
        )
        
        if response.status_code != 200:
            return Response(
                content='<h1>Ошибка авторизации</h1><script>setTimeout(() => window.close(), 2000);</script>',
                media_type="text/html"
            )
        
        access_token = response.json()["access_token"]
        yandex_tokens.add(access_token)
        
        return Response(
            content=f'''
            <html>
                <body>
                    <h1>Авторизация успешна!</h1>
                    <p>Вы можете закрыть это окно.</p>
                    <script>
                        window.opener.postMessage({{type: 'yandex_auth_success', token: '{access_token}'}}, '*');
                        setTimeout(() => window.close(), 2000);
                    </script>
                </body>
            </html>
            ''',
            media_type="text/html"
        )

@app.get("/api/yandex/check")
async def check_yandex_auth(token: Optional[str] = None):
    """Проверка авторизации Яндекс Диска"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        env_token = os.getenv("YANDEX_DISK_TOKEN")
        if env_token:
            token = env_token
    
    if not token:
        return {"authenticated": False}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://cloud-api.yandex.net/v1/disk",
                headers={"Authorization": f"OAuth {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                yandex_tokens.add(token)
                return {"authenticated": True, "token": token, "from_env": token == os.getenv("YANDEX_DISK_TOKEN")}
        except:
            pass
    
    return {"authenticated": False}

@app.get("/api/yandex/get-env-token")
async def get_env_token():
    """Получение токена из .env (если есть)"""
    env_token = os.getenv("YANDEX_DISK_TOKEN")
    if env_token:
        # Проверяем валидность токена
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    "https://cloud-api.yandex.net/v1/disk",
                    headers={"Authorization": f"OAuth {env_token}"},
                    timeout=10.0
                )
                if response.status_code == 200:
                    return {"has_token": True, "valid": True}
            except:
                pass
        return {"has_token": True, "valid": False}
    return {"has_token": False, "valid": False}

@app.get("/api/yandex/folders")
async def get_yandex_folders(token: Optional[str] = None):
    """Получение списка папок Яндекс Диска"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources",
            params={"path": "/", "limit": 1000},
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch folders")
        
        data = response.json()
        folders = [
            {"name": item["name"], "path": item["path"]}
            for item in data.get("_embedded", {}).get("items", [])
            if item.get("type") == "dir"
        ]
        
        return {"folders": folders}

@app.get("/api/yandex/public-files")
async def get_public_yandex_files(public_url: str = Query(...)):
    """Получение списка файлов из публичной папки Яндекс Диска"""
    logger = logging.getLogger(__name__)
    
    try:
        # Извлекаем ID папки из URL
        # Формат: https://disk.yandex.ru/d/-uXMLsCHrFtxzg или https://disk.yandex.ru/client/disk/...
        folder_id = None
        folder_path = None
        
        # Пробуем формат /d/ID
        match = re.search(r'/d/([^/?]+)', public_url)
        if match:
            folder_id = match.group(1)
            folder_url = f"https://disk.yandex.ru/d/{folder_id}"
        else:
            # Пробуем формат /client/disk/PATH
            match = re.search(r'/client/disk/([^/?]+)', public_url)
            if match:
                folder_path = match.group(1)
                # Декодируем URL-encoded путь (если он закодирован)
                from urllib.parse import unquote
                try:
                    # Пробуем декодировать - если URL уже содержит кириллицу, unquote вернет его как есть
                    decoded_path = unquote(folder_path)
                    folder_path = decoded_path
                except:
                    # Если декодирование не удалось, используем оригинальный путь
                    pass
                folder_url = public_url.split('?')[0]  # Используем оригинальный URL
            else:
                raise HTTPException(status_code=400, detail="Invalid Yandex Disk URL format. Expected /d/ID or /client/disk/PATH")
        
        logger.info(f"Parsing Yandex Disk folder: folder_id={folder_id}, folder_path={folder_path}")
        
        # Парсим публичную страницу
        async with httpx.AsyncClient() as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
            }
            response = await client.get(
                folder_url,
                headers=headers,
                timeout=30.0,
                follow_redirects=True
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch public folder")
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            files = []
            seen_names = set()
            seen_urls = set()
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg']
            
            # Метод 1: Ищем ссылки на файлы в HTML (улучшенный)
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '').strip()
                # Пробуем разные способы получить имя файла
                name = (
                    link.get_text(strip=True) or 
                    link.get('title', '') or 
                    link.get('data-name', '') or
                    link.get('aria-label', '') or
                    ''
                )
                
                # Если имени нет в тексте, пробуем извлечь из href
                if not name and href:
                    name = href.split('/')[-1].split('?')[0]
                
                if href and name and name not in seen_names:
                    # Проверяем расширение в имени или в href
                    name_lower = name.lower()
                    href_lower = href.lower()
                    if any(ext in name_lower for ext in image_extensions) or any(ext in href_lower for ext in image_extensions):
                        if href.startswith('http'):
                            file_url = href.split('?')[0]  # Убираем query параметры
                        elif href.startswith('/'):
                            file_url = f"https://disk.yandex.ru{href.split('?')[0]}"
                        else:
                            if folder_id:
                                file_url = f"https://disk.yandex.ru/d/{folder_id}/{href.split('?')[0]}"
                            else:
                                # Для формата /client/disk/ используем базовый URL
                                base_url = folder_url.rsplit('/', 1)[0] if folder_url else "https://disk.yandex.ru"
                                file_url = f"{base_url}/{href.split('?')[0]}"
                        
                        if file_url not in seen_urls:
                            files.append({
                                "name": name,
                                "path": file_url,
                                "url": file_url,
                                "mime_type": "image/jpeg"
                            })
                            seen_names.add(name)
                            seen_urls.add(file_url)
            
            # Метод 2: Ищем изображения напрямую (img теги)
            img_tags = soup.find_all('img', src=True)
            for img in img_tags:
                src = img.get('src', '').strip()
                alt = img.get('alt', '').strip()
                title = img.get('title', '').strip()
                data_name = img.get('data-name', '').strip()
                
                name = alt or title or data_name or src.split('/')[-1].split('?')[0]
                
                if src and name and name not in seen_names:
                    if any(ext in name.lower() for ext in image_extensions) or any(ext in src.lower() for ext in image_extensions):
                        if src.startswith('http'):
                            file_url = src.split('?')[0]
                        elif src.startswith('/'):
                            file_url = f"https://disk.yandex.ru{src.split('?')[0]}"
                        else:
                            if folder_id:
                                file_url = f"https://disk.yandex.ru/d/{folder_id}/{src.split('?')[0]}"
                            else:
                                base_url = folder_url.rsplit('/', 1)[0] if folder_url else "https://disk.yandex.ru"
                                file_url = f"{base_url}/{src.split('?')[0]}"
                        
                        if file_url not in seen_urls:
                            files.append({
                                "name": name,
                                "path": file_url,
                                "url": file_url,
                                "mime_type": "image/jpeg"
                            })
                            seen_names.add(name)
                            seen_urls.add(file_url)
            
            # Метод 3: Ищем данные в скриптах (JSON) - улучшенный
            scripts = soup.find_all('script')
            for script in scripts:
                if not script.string:
                    continue
                
                script_text = script.string
                # Расширенный поиск JSON данных
                if any(keyword in script_text for keyword in ['items', 'resources', 'files', 'itemsList', 'fileList', 'photos', 'images']):
                    try:
                        # Ищем различные JSON паттерны
                        json_patterns = [
                            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
                            r'window\.__DATA__\s*=\s*({.+?});',
                            r'"items"\s*:\s*\[(.*?)\]',
                            r'"resources"\s*:\s*\[(.*?)\]',
                            r'"files"\s*:\s*\[(.*?)\]',
                            r'\{[^{}]*"name"[^{}]*"path"[^{}]*\}',
                            r'\[[^\]]*\{[^{}]*"name"[^{}]*\}[^\]]*\]'
                        ]
                        
                        for pattern in json_patterns:
                            matches = re.finditer(pattern, script_text, re.DOTALL)
                            for match in matches:
                                try:
                                    json_str = match.group(1) if match.groups() else match.group(0)
                                    json_str = json_str.strip().rstrip(';')
                                    
                                    # Пробуем распарсить как JSON
                                    try:
                                        data = json.loads(json_str)
                                    except:
                                        # Если не JSON, пробуем найти объекты через regex
                                        continue
                                    
                                    items = []
                                    if isinstance(data, dict):
                                        # Рекурсивно ищем items в словаре
                                        def find_items(obj, depth=0):
                                            if depth > 5:  # Ограничение глубины
                                                return []
                                            result = []
                                            if isinstance(obj, dict):
                                                if 'name' in obj and ('path' in obj or 'url' in obj or 'href' in obj):
                                                    result.append(obj)
                                                for v in obj.values():
                                                    result.extend(find_items(v, depth+1))
                                            elif isinstance(obj, list):
                                                for item in obj:
                                                    result.extend(find_items(item, depth+1))
                                            return result
                                        
                                        items = find_items(data)
                                        if not items:
                                            items = data.get('items', data.get('resources', data.get('files', data.get('data', []))))
                                    elif isinstance(data, list):
                                        items = data
                                    
                                    for item in items:
                                        if isinstance(item, dict):
                                            name = (
                                                item.get('name') or 
                                                item.get('title') or 
                                                item.get('filename') or 
                                                item.get('displayName') or
                                                ''
                                            )
                                            
                                            if name and name not in seen_names:
                                                name_lower = name.lower()
                                                if any(ext in name_lower for ext in image_extensions):
                                                    file_url = (
                                                        item.get('file') or 
                                                        item.get('href') or 
                                                        item.get('url') or 
                                                        item.get('path') or
                                                        item.get('downloadUrl') or
                                                        ''
                                                    )
                                                    
                                                    if file_url:
                                                        if not file_url.startswith('http'):
                                                            if file_url.startswith('/'):
                                                                file_url = f"https://disk.yandex.ru{file_url}"
                                                            else:
                                                                if folder_id:
                                                                    file_url = f"https://disk.yandex.ru/d/{folder_id}/{file_url}"
                                                                else:
                                                                    base_url = folder_url.rsplit('/', 1)[0] if folder_url else "https://disk.yandex.ru"
                                                                    file_url = f"{base_url}/{file_url}"
                                                        
                                                        file_url = file_url.split('?')[0]
                                                        
                                                        if file_url not in seen_urls:
                                                            files.append({
                                                                "name": name,
                                                                "path": file_url,
                                                                "url": file_url,
                                                                "mime_type": item.get('mime_type', item.get('mimeType', 'image/jpeg'))
                                                            })
                                                            seen_names.add(name)
                                                            seen_urls.add(file_url)
                                except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as e:
                                    continue
                    except Exception as e:
                        continue
            
            # Метод 4: Ищем через data-атрибуты и классы
            elements = soup.find_all(attrs={'data-name': True})
            for elem in elements:
                name = elem.get('data-name', '').strip()
                href = (
                    elem.get('href', '').strip() or 
                    elem.get('data-href', '').strip() or
                    elem.get('data-url', '').strip() or
                    (elem.find('a', href=True) and elem.find('a', href=True).get('href', '').strip()) or
                    ''
                )
                
                if name and href and name not in seen_names:
                    name_lower = name.lower()
                    if any(ext in name_lower for ext in image_extensions):
                        if not href.startswith('http'):
                            if href.startswith('/'):
                                href = f"https://disk.yandex.ru{href}"
                            else:
                                if folder_id:
                                    href = f"https://disk.yandex.ru/d/{folder_id}/{href}"
                                else:
                                    base_url = folder_url.rsplit('/', 1)[0] if folder_url else "https://disk.yandex.ru"
                                    href = f"{base_url}/{href}"
                        
                        href = href.split('?')[0]
                        
                        if href not in seen_urls:
                            files.append({
                                "name": name,
                                "path": href,
                                "url": href,
                                "mime_type": "image/jpeg"
                            })
                            seen_names.add(name)
                            seen_urls.add(href)
            
            # Метод 5: Ищем через классы с префиксами Яндекс Диска
            disk_elements = soup.find_all(class_=re.compile(r'(file|item|resource|photo|image)', re.I))
            for elem in disk_elements:
                link = elem.find('a', href=True)
                if link:
                    href = link.get('href', '').strip()
                    name = (
                        link.get_text(strip=True) or 
                        link.get('title', '') or 
                        elem.get('data-name', '') or
                        href.split('/')[-1].split('?')[0] or
                        ''
                    )
                    
                    if href and name and name not in seen_names:
                        name_lower = name.lower()
                        href_lower = href.lower()
                        if any(ext in name_lower for ext in image_extensions) or any(ext in href_lower for ext in image_extensions):
                            if not href.startswith('http'):
                                if href.startswith('/'):
                                    href = f"https://disk.yandex.ru{href}"
                                else:
                                    if folder_id:
                                        href = f"https://disk.yandex.ru/d/{folder_id}/{href}"
                                    else:
                                        base_url = folder_url.rsplit('/', 1)[0] if folder_url else "https://disk.yandex.ru"
                                        href = f"{base_url}/{href}"
                            
                            href = href.split('?')[0]
                            
                            if href not in seen_urls:
                                files.append({
                                    "name": name,
                                    "path": href,
                                    "url": href,
                                    "mime_type": "image/jpeg"
                                })
                                seen_names.add(name)
                            seen_urls.add(href)
            
            logger.info(f"Found {len(files)} files using {len(seen_names)} unique names")
            
            # Если файлов не найдено, возвращаем информацию для отладки
            if len(files) == 0:
                logger.warning(f"No files found. HTML length: {len(html)}, Links found: {len(all_links)}, Images found: {len(img_tags)}")
                # Сохраняем HTML для отладки (опционально, можно закомментировать в продакшене)
                # with open(f"debug_{folder_id}.html", "w", encoding="utf-8") as f:
                #     f.write(html)
            
            return {"files": files, "folder_id": folder_id, "folder_path": folder_path, "total_found": len(files)}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing public folder: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error parsing public folder: {str(e)}")

@app.get("/api/yandex/files")
async def get_yandex_files(path: str, token: Optional[str] = None):
    """Получение списка файлов в папке"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources",
            params={"path": path, "limit": 1000},
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch files")
        
        data = response.json()
        files = [
            {
                "name": item["name"],
                "path": item["path"],
                "mime_type": item.get("mime_type"),
                "size": item.get("size")
            }
            for item in data.get("_embedded", {}).get("items", [])
            if item.get("type") == "file" and item.get("mime_type", "").startswith("image/")
        ]
        
        return {"files": files}

@app.get("/api/yandex/structure")
async def get_yandex_structure(
    path: str = Query("/"),
    token: Optional[str] = Query(None),
    lazy: bool = Query(True)
):
    """Получение структуры папок и файлов с Yandex Disk (ленивая загрузка - только один уровень)"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://cloud-api.yandex.net/v1/disk/resources",
                params={"path": path, "limit": 1000},
                headers={"Authorization": f"OAuth {token}"},
                timeout=30.0
            )
            
            if response.status_code != 200:
                return {"path": path, "structure": []}
            
            data = response.json()
            items = data.get("_embedded", {}).get("items", [])
            
            result = []
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff']
            
            for item in items:
                item_type = item.get("type")
                name = item.get("name")
                item_path = item.get("path", path)
                
                if item_type == "dir":
                    # Для папок не загружаем содержимое сразу (ленивая загрузка)
                    result.append({
                        "name": name,
                        "path": item_path,
                        "type": "dir",
                        "depth": 0,
                        "children": None,  # Будет загружено по требованию
                        "has_children": True  # Предполагаем, что есть дети (можно проверить через API)
                    })
                else:
                    # Показываем только изображения
                    name_lower = name.lower()
                    if any(ext in name_lower for ext in image_extensions) or item.get("mime_type", "").startswith("image/"):
                        result.append({
                            "name": name,
                            "path": item_path,
                            "type": "file",
                            "depth": 0,
                            "mime_type": item.get("mime_type"),
                            "size": item.get("size")
                        })
            
            return {
                "path": path,
                "structure": result
            }
            
        except Exception as e:
            logging.error(f"Error listing folder {path}: {str(e)}")
            return {"path": path, "structure": []}

@app.get("/api/yandex/account-info")
async def get_yandex_account_info(token: Optional[str] = Query(None)):
    """Получение информации о аккаунте Yandex Disk"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://cloud-api.yandex.net/v1/disk",
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch account info")
        
        data = response.json()
        total_space = data.get("total_space", 0)
        used_space = data.get("used_space", 0)
        
        return {
            "login": data.get("user", {}).get("login", "Unknown"),
            "display_name": data.get("user", {}).get("display_name", "Unknown"),
            "uid": data.get("user", {}).get("uid", "Unknown"),
            "total_space_gb": round(total_space / (1024**3), 2) if total_space else 0,
            "used_space_gb": round(used_space / (1024**3), 2) if used_space else 0,
            "free_space_gb": round((total_space - used_space) / (1024**3), 2) if total_space and used_space else 0
        }

@app.get("/api/yandex/download-public")
async def download_public_file(file_url: str = Query(..., alias="url")):
    """Скачивание публичного файла с Яндекс Диска"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Referer': 'https://disk.yandex.ru/'
            }
            response = await client.get(file_url, headers=headers, timeout=60.0, follow_redirects=True)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to download file")
            
            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "application/octet-stream")
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")

@app.get("/api/yandex/download")
async def download_yandex_file(path: str, token: Optional[str] = None):
    """Скачивание файла с Яндекс Диска (OAuth)"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        # Получаем ссылку для скачивания
        link_response = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources/download",
            params={"path": path},
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if link_response.status_code != 200:
            raise HTTPException(status_code=link_response.status_code, detail="Failed to get download link")
        
        download_url = link_response.json()["href"]
        
        # Скачиваем файл (Yandex Disk возвращает 302 redirect, нужно следовать за ним)
        file_response = await client.get(download_url, timeout=60.0, follow_redirects=True)
        
        if file_response.status_code != 200:
            raise HTTPException(status_code=file_response.status_code, detail=f"Failed to download file: {file_response.status_code}")
        
        # Определяем content-type из заголовков или по расширению файла
        content_type = file_response.headers.get("content-type", "application/octet-stream")
        if content_type == "application/octet-stream":
            # Пытаемся определить тип по расширению из пути
            path_lower = path.lower()
            if path_lower.endswith(('.jpg', '.jpeg')):
                content_type = "image/jpeg"
            elif path_lower.endswith('.png'):
                content_type = "image/png"
            elif path_lower.endswith('.gif'):
                content_type = "image/gif"
            elif path_lower.endswith('.webp'):
                content_type = "image/webp"
        
        return Response(
            content=file_response.content,
            media_type=content_type
        )

@app.post("/api/yandex/upload")
async def upload_yandex_file(
    file: UploadFile = File(...),
    path: str = Form(...),
    token: Optional[str] = Form(None)
):
    """Загрузка файла на Яндекс Диск"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    file_bytes = await file.read()
    
    async with httpx.AsyncClient() as client:
        # Получаем ссылку для загрузки
        link_response = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources/upload",
            params={"path": path, "overwrite": "true"},
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if link_response.status_code != 200:
            raise HTTPException(status_code=link_response.status_code, detail="Failed to get upload link")
        
        upload_url = link_response.json()["href"]
        
        # Загружаем файл
        upload_response = await client.put(
            upload_url,
            content=file_bytes,
            headers={"Content-Type": file.content_type or "application/octet-stream"},
            timeout=60.0
        )
        
        if upload_response.status_code not in [201, 202]:
            raise HTTPException(status_code=upload_response.status_code, detail="Failed to upload file")
        
        return {"success": True, "path": path}

@app.post("/api/yandex/create-folder")
async def create_yandex_folder(path: str, token: Optional[str] = Form(None)):
    """Создание папки на Яндекс Диске"""
    # Если токен не передан, пробуем использовать токен из .env
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        response = await client.put(
            "https://cloud-api.yandex.net/v1/disk/resources",
            params={"path": path},
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        # Игнорируем ошибку если папка уже существует
        if response.status_code == 409:
            return {"success": True, "path": path, "exists": True}
        
        if response.status_code not in [201, 202]:
            raise HTTPException(status_code=response.status_code, detail="Failed to create folder")
        
        return {"success": True, "path": path}

@app.post("/api/batch-process-products")
async def batch_process_products(
    public_url: str = Form(...),
    model: str = Form("replicate"),
    apiKey: Optional[str] = Form(None),
    token: Optional[str] = Form(None)
):
    """
    Batch processing продуктов из папки Яндекс Диска.
    Ожидается структура: папки с продуктами, в каждой папке 5 фотографий.
    Все фотографии обрабатываются через удаление фона.
    Для первой фотографии каждого продукта создается версия с дизайном.
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Получаем список файлов из папки
        files_response = await get_public_yandex_files(public_url=public_url)
        files = files_response.get("files", [])
        
        if not files:
            raise HTTPException(status_code=404, detail="No files found in folder")
        
        # Группируем файлы по продуктам
        # Предполагаем, что файлы организованы в папки или имеют паттерн именования
        # Для простоты, группируем по первым символам имени (до первого числа или разделителя)
        products = {}
        for file in files:
            name = file.get("name", "")
            # Извлекаем имя продукта (до первого числа, подчеркивания или дефиса)
            product_match = re.match(r'^([^0-9_\-]+)', name)
            if product_match:
                product_name = product_match.group(1).strip()
            else:
                # Если паттерн не найден, используем имя файла без расширения
                product_name = name.rsplit('.', 1)[0]
            
            if product_name not in products:
                products[product_name] = []
            products[product_name].append(file)
        
        logger.info(f"Found {len(products)} products, total files: {len(files)}")
        
        # Получаем API ключ
        api_key = get_api_key(model, apiKey)
        if not api_key:
            raise HTTPException(status_code=400, detail="API key not provided")
        
        results = []
        processed_count = 0
        total_count = len(files)
        
        # Обрабатываем каждый продукт
        for product_name, product_files in products.items():
            # Сортируем файлы по имени для консистентности
            product_files.sort(key=lambda x: x.get("name", ""))
            
            product_results = {
                "product_name": product_name,
                "files": [],
                "design_file": None
            }
            
            # Обрабатываем каждое фото продукта
            for idx, file_info in enumerate(product_files):
                try:
                    # Скачиваем файл
                    file_url = file_info.get("url") or file_info.get("path")
                    async with httpx.AsyncClient() as client:
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Referer': 'https://disk.yandex.ru/'
                        }
                        file_response = await client.get(file_url, headers=headers, timeout=60.0, follow_redirects=True)
                        if file_response.status_code != 200:
                            logger.warning(f"Failed to download {file_info.get('name')}: {file_response.status_code}")
                            continue
                        image_bytes = file_response.content
                    
                    # Обрабатываем через удаление фона
                    processed_bytes = await MODELS[model](image_bytes, api_key, None)
                    
                    processed_count += 1
                    
                    # Для первой фотографии создаем версию с дизайном
                    if idx == 0:
                        try:
                            # Используем внутренний вызов place_on_background
                            processed_file_obj = io.BytesIO(processed_bytes)
                            processed_file_obj.name = "processed.png"
                            
                            # Получаем путь к фону
                            background_paths = [
                                "/app/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg",
                                os.path.expanduser("~/background_remover/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg"),
                                "./background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg",
                                "background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg"
                            ]
                            
                            background_path = None
                            for path in background_paths:
                                if os.path.exists(path):
                                    background_path = path
                                    break
                            
                            if background_path:
                                with open(background_path, 'rb') as f:
                                    background_bytes = f.read()
                                
                                background_file_obj = io.BytesIO(background_bytes)
                                background_file_obj.name = "background.jpeg"
                                
                                # Используем replicate для размещения на фоне
                                os.environ["REPLICATE_API_TOKEN"] = api_key
                                
                                default_prompt = """Add the product from @img2 to the image @img1. The product must levitate directly above the podium, barely touching the podium surface, with a visible contact shadow."""
                                
                                processed_file_obj.seek(0)
                                background_file_obj.seek(0)
                                
                                model_input = {
                                    "images": [background_file_obj, processed_file_obj],
                                    "prompt": default_prompt,
                                    "aspect_ratio": "4:3"
                                }
                                
                                design_output = await asyncio.to_thread(
                                    replicate.run,
                                    "prunaai/p-image-edit",
                                    input=model_input
                                )
                                
                                design_bytes = None
                                if hasattr(design_output, 'read'):
                                    design_bytes = design_output.read()
                                elif isinstance(design_output, str):
                                    async with httpx.AsyncClient() as http_client:
                                        response = await http_client.get(design_output, timeout=60.0)
                                        if response.status_code == 200:
                                            design_bytes = response.content
                                elif isinstance(design_output, list) and len(design_output) > 0:
                                    first_item = design_output[0]
                                    if hasattr(first_item, 'read'):
                                        design_bytes = first_item.read()
                                    elif isinstance(first_item, str):
                                        async with httpx.AsyncClient() as http_client:
                                            response = await http_client.get(first_item, timeout=60.0)
                                            if response.status_code == 200:
                                                design_bytes = response.content
                                
                                if design_bytes:
                                    product_results["design_file"] = {
                                        "name": f"{product_name}_design.png",
                                        "data": base64.b64encode(design_bytes).decode('utf-8'),
                                        "size": len(design_bytes)
                                    }
                        except Exception as e:
                            logger.warning(f"Failed to create design version for {product_name}: {str(e)}")
                    
                    # Сохраняем обработанное изображение
                    product_results["files"].append({
                        "name": file_info.get("name", ""),
                        "processed_name": f"{product_name}_{idx + 1}_processed.png",
                        "data": base64.b64encode(processed_bytes).decode('utf-8'),
                        "size": len(processed_bytes)
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing {file_info.get('name')}: {str(e)}")
                    continue
            
            results.append(product_results)
        
        return {
            "success": True,
            "products_processed": len(results),
            "total_files_processed": processed_count,
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch processing: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch processing error: {str(e)}")

async def send_progress_update(message: dict):
    """Helper function to format progress update as SSE"""
    return f"data: {json_lib.dumps(message, ensure_ascii=False)}\n\n"

@app.post("/api/batch-process-folders")
async def batch_process_folders(
    base_path: str = Form("/"),
    model: str = Form("replicate"),
    apiKey: Optional[str] = Form(None),
    token: Optional[str] = Form(None),
    width: int = Form(1200),
    height: int = Form(1200),
    output_folder: str = Form("")  # Будет генерироваться автоматически
):
    """
    Batch processing folderów с Yandex Disk.
    Обрабатывает N папок, в каждой папке по 5 фотографий.
    Все фотографии переносятся на белый фон с заданным размером.
    Для первой фотографии создается версия с дизайном.
    Все результаты сохраняются на Yandex Disk.
    """
    logger = logging.getLogger(__name__)
    cost_logger = logging.getLogger('costs')
    
    # Стоимость операций
    COST_BACKGROUND_REMOVAL = 0.018  # $0.018 per image
    COST_P_IMAGE_EDIT = 0.14  # $0.14 per image
    
    # Счетчики для расчета стоимости
    background_removal_count = 0
    p_image_edit_count = 0
    
    try:
        # Получаем токен (из запроса или env variables)
        if not token:
            token = os.getenv("YANDEX_DISK_TOKEN")
        
        if not token:
            logger.error("Yandex Disk token not found in request or environment variables")
            raise HTTPException(
                status_code=401, 
                detail="Yandex Disk token not provided. Please authenticate via Yandex Disk OAuth or set YANDEX_DISK_TOKEN in Railway variables."
            )
        
        logger.info(f"Using Yandex Disk token: {'from request' if token != os.getenv('YANDEX_DISK_TOKEN') else 'from env variables'}")
        
        # Получаем API ключ
        api_key = get_api_key(model, apiKey)
        if not api_key:
            # Логируем для отладки
            logger.error(f"API key not found for model: {model}")
            logger.error(f"apiKey from request: {'provided' if apiKey else 'not provided'}")
            if model == "replicate":
                env_key_exists = bool(os.getenv('REPLICATE_API_KEY'))
                logger.error(f"REPLICATE_API_KEY in env: {'exists' if env_key_exists else 'NOT FOUND - please set in Railway variables'}")
                raise HTTPException(
                    status_code=400, 
                    detail=f"REPLICATE_API_KEY not found. Please set REPLICATE_API_KEY in Railway variables (Environment Variables section)."
                )
            else:
                raise HTTPException(
                    status_code=400, 
                    detail=f"API key not provided for model {model}. Please set it in Railway variables or provide it in the request."
                )
        
        # Проверяем, является ли base_path URL или путем
        # Если это URL, используем API для публичных папок
        use_public_api = False
        public_key = None
        actual_path = base_path
        
        if base_path.startswith("http"):
            # Это публичный URL, нужно извлечь ID
            logger.info(f"Detected public URL, extracting folder ID: {base_path}")
            
            # Извлекаем ID из URL формата https://disk.yandex.ru/d/ID
            match = re.search(r'/d/([^/?]+)', base_path)
            if match:
                public_key = match.group(1)
                use_public_api = True
                logger.info(f"Extracted public folder ID: {public_key}")
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Неверный формат URL. Ожидается формат: https://disk.yandex.ru/d/ID"
                )
        
        # Получаем список папок
        logger.info(f"Fetching folders from Yandex Disk, path: {actual_path}, use_public_api: {use_public_api}")
        async with httpx.AsyncClient() as client:
            try:
                if use_public_api:
                    # Используем API для публичных папок
                    response = await client.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={"public_key": public_key, "limit": 1000},
                        headers={"Authorization": f"OAuth {token}"},
                        timeout=30.0
                    )
                else:
                    # Используем обычный API для приватных папок
                    response = await client.get(
                        "https://cloud-api.yandex.net/v1/disk/resources",
                        params={"path": actual_path, "limit": 1000},
                        headers={"Authorization": f"OAuth {token}"},
                        timeout=30.0
                    )
                
                logger.info(f"Yandex Disk API response status: {response.status_code}")
                
                if response.status_code != 200:
                    try:
                        error_json = response.json()
                        error_text = str(error_json)
                    except:
                        error_text = response.text
                    
                    logger.error(f"Yandex Disk API error: {response.status_code}, response: {error_text}")
                    
                    if response.status_code == 401:
                        raise HTTPException(
                            status_code=401, 
                            detail="Yandex Disk authentication failed. Token is invalid or expired. Please re-authenticate via OAuth or check YANDEX_DISK_TOKEN in Railway variables."
                        )
                    elif response.status_code == 403:
                        raise HTTPException(
                            status_code=403,
                            detail="Access forbidden. Check if the token has proper permissions to access Yandex Disk."
                        )
                    elif response.status_code == 404:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Path not found: {base_path}. Please check if the path exists on Yandex Disk."
                        )
                    elif response.status_code == 405:
                        raise HTTPException(
                            status_code=405,
                            detail="Method not allowed. This might indicate an issue with Yandex Disk API. Please check the token and try again."
                        )
                    else:
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"Yandex Disk API error ({response.status_code}): {error_text[:300]}"
                        )
            except httpx.RequestError as e:
                logger.error(f"Request error when fetching folders: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Network error when accessing Yandex Disk: {str(e)}")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Unexpected error when fetching folders: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
            
            data = response.json()
            
            # Для публичных папок структура может быть немного другой
            items = data.get("_embedded", {}).get("items", [])
            if not items and use_public_api:
                # Пробуем альтернативную структуру для публичных папок
                items = data.get("items", [])
            
            folders = []
            for item in items:
                if item.get("type") == "dir":
                    folder_name = item.get("name", "")
                    # Для публичных папок сохраняем public_key для доступа к подпапкам
                    if use_public_api:
                        # Для подпапок в публичной папке используем тот же public_key
                        folder_path = folder_name  # Относительный путь
                    else:
                        folder_path = item.get("path", "")
                    
                    folders.append({
                        "name": folder_name, 
                        "path": folder_path, 
                        "public_key": public_key if use_public_api else None
                    })
        
        logger.info(f"Found {len(folders)} folders to process")
        cost_logger.info(f"=== Начало обработки {len(folders)} папок ===")
        cost_logger.info(f"Базовый путь: {base_path}, Размер выходных изображений: {width}x{height}")
        
        # Создаем async generator для streaming response
        async def generate_progress():
            results = []
            
            # Отправляем начальное сообщение
            yield await send_progress_update({
                "type": "start",
                "total_folders": len(folders),
                "message": f"Начало обработки {len(folders)} папок"
            })
            
            # Обрабатываем каждую папку
            for folder_idx, folder in enumerate(folders, 1):
                folder_name = folder["name"]
                folder_path = folder["path"]
                
                logger.info(f"Processing folder {folder_idx}/{len(folders)}: {folder_name}")
                cost_logger.info(f"--- Обработка папки {folder_idx}/{len(folders)}: {folder_name} ---")
                
                # Отправляем информацию о начале обработки папки
                yield await send_progress_update({
                    "type": "folder_start",
                    "folder_index": folder_idx,
                    "total_folders": len(folders),
                    "folder_name": folder_name,
                    "message": f"Обработка папки {folder_idx}/{len(folders)}: {folder_name}"
                })
                
                try:
                    # Получаем файлы из папки
                    folder_public_key = folder.get("public_key")
                    is_public_subfolder = folder_public_key is not None
                    
                    async with httpx.AsyncClient() as client:
                        if is_public_subfolder:
                            # Используем API для публичных папок
                            response = await client.get(
                                "https://cloud-api.yandex.net/v1/disk/public/resources",
                                params={"public_key": folder_public_key, "path": folder_path, "limit": 1000},
                                headers={"Authorization": f"OAuth {token}"},
                                timeout=30.0
                            )
                        else:
                            # Используем обычный API
                            response = await client.get(
                                "https://cloud-api.yandex.net/v1/disk/resources",
                                params={"path": folder_path, "limit": 1000},
                                headers={"Authorization": f"OAuth {token}"},
                                timeout=30.0
                            )
                        
                        if response.status_code != 200:
                            logger.warning(f"Failed to fetch files from folder {folder_name}: {response.status_code}")
                            continue
                        
                        data = response.json()
                        # Для публичных папок структура может быть немного другой
                        items = data.get("_embedded", {}).get("items", [])
                        if not items and is_public_subfolder:
                            items = data.get("items", [])
                        
                        files = [
                            item for item in items
                            if item.get("type") == "file" and item.get("mime_type", "").startswith("image/")
                        ]
                        
                        # Сортируем файлы по имени и берем первые 5
                        files.sort(key=lambda x: x.get("name", ""))
                        files = files[:5]
                        
                        if len(files) < 5:
                            logger.warning(f"Folder {folder_name} has only {len(files)} images, expected 5")
                    
                    # Создаем папку для результатов
                    # Используем имя папки + "_Обработанный"
                    output_folder_name = f"{folder_name}_Обработанный"
                    
                    # Для публичных папок сохраняем результаты в корневой папке пользователя
                    if folder.get("public_key"):
                        # Для публичных папок создаем структуру в корневой папке
                        # Используем имя публичной папки как базовую папку
                        base_public_folder_name = "Публичные_обработанные"
                        output_path = f"/{base_public_folder_name}/{folder_name}/{output_folder_name}"
                    else:
                        # Для обычных папок создаем рядом с исходной папкой
                        # Если folder_path это полный путь, берем родительскую папку
                        if folder_path.startswith('/'):
                            # Извлекаем родительскую папку
                            parent_path = '/'.join(folder_path.rstrip('/').split('/')[:-1]) if '/' in folder_path else '/'
                            output_path = f"{parent_path}/{output_folder_name}" if parent_path != '/' else f"/{output_folder_name}"
                        else:
                            # Относительный путь - создаем рядом
                            output_path = f"{folder_path}_Обработанный"
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.put(
                            "https://cloud-api.yandex.net/v1/disk/resources",
                            params={"path": output_path},
                            headers={"Authorization": f"OAuth {token}"},
                            timeout=30.0
                        )
                        # Игнорируем ошибку если папка уже существует
                    
                    folder_results = {
                    "folder_name": folder_name,
                    "folder_path": folder_path,
                    "files_processed": 0,
                    "design_created": False,
                    "errors": []
                    }
                    
                    # Обрабатываем каждое фото
                    for file_idx, file_info in enumerate(files):
                        try:
                            file_name = file_info.get("name", "")
                            file_path = file_info.get("path", "")
                            
                            logger.info(f"  Processing file {file_idx + 1}/5: {file_name}")
                            
                            # Отправляем информацию о начале обработки файла
                            yield await send_progress_update({
                                "type": "file_start",
                                "folder_name": folder_name,
                                "folder_index": folder_idx,
                                "file_index": file_idx + 1,
                                "total_files": len(files),
                                "file_name": file_name,
                                "message": f"Обработка файла {file_idx + 1}/{len(files)}: {file_name}"
                            })
                            
                            # Скачиваем файл
                            file_is_public = folder.get("public_key") is not None
                            
                            async with httpx.AsyncClient() as client:
                                if file_is_public:
                                    # Для публичных файлов используем другой endpoint
                                    # file_path для публичных файлов может быть относительным путем
                                    # Нужно использовать полный путь: folder_path/file_name
                                    public_file_path = f"{folder_path}/{file_name}" if folder_path else file_name
                                    link_response = await client.get(
                                        "https://cloud-api.yandex.net/v1/disk/public/resources/download",
                                        params={"public_key": folder.get("public_key"), "path": public_file_path},
                                        headers={"Authorization": f"OAuth {token}"},
                                        timeout=30.0
                                    )
                                else:
                                    # Для приватных файлов используем обычный endpoint
                                    link_response = await client.get(
                                        "https://cloud-api.yandex.net/v1/disk/resources/download",
                                        params={"path": file_path},
                                        headers={"Authorization": f"OAuth {token}"},
                                        timeout=30.0
                                    )
                                
                                if link_response.status_code != 200:
                                    raise Exception(f"Failed to get download link: {link_response.status_code}")
                                
                                download_url = link_response.json()["href"]
                                file_response = await client.get(download_url, timeout=60.0, follow_redirects=True)
                                
                                if file_response.status_code != 200:
                                    raise Exception(f"Failed to download file: {file_response.status_code}")
                                
                                image_bytes = file_response.content
                            
                            # Обрабатываем через удаление фона
                            yield await send_progress_update({
                            "type": "processing",
                            "folder_name": folder_name,
                            "file_name": file_name,
                            "step": "background_removal",
                                "message": f"Удаление фона: {file_name}"
                            })
                            
                            processed_bytes = await MODELS[model](image_bytes, api_key, None)
                            background_removal_count += 1
                            
                            # Размещаем на белом фоне с заданным размером
                            processed_img = Image.open(io.BytesIO(processed_bytes))
                            template_width = max(100, min(5000, width))
                            template_height = max(100, min(5000, height))
                            template_img = Image.new("RGB", (template_width, template_height), "white")
                            
                            img_width, img_height = processed_img.size
                            scale_width = template_width / img_width
                            scale_height = template_height / img_height
                            scale = min(scale_width, scale_height)
                            
                            new_width = int(img_width * scale)
                            new_height = int(img_height * scale)
                            processed_img = processed_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                            
                            x = (template_width - new_width) // 2
                            y = (template_height - new_height) // 2
                            
                            result = template_img.copy()
                            if processed_img.mode == "RGBA":
                                result.paste(processed_img, (x, y), processed_img)
                            else:
                                result.paste(processed_img, (x, y))
                            
                            # Сохраняем в bytes
                            output = io.BytesIO()
                            result.save(output, format="PNG")
                            output.seek(0)
                            white_bg_bytes = output.read()
                            
                            # Сохраняем на Yandex Disk
                            save_name = f"{file_name.rsplit('.', 1)[0]}_processed.png"
                            save_path = f"{output_path}/{save_name}"
                            
                            yield await send_progress_update({
                                "type": "saving",
                                "folder_name": folder_name,
                                "file_name": file_name,
                                "saved_name": save_name,
                                "save_path": save_path,
                                "message": f"Сохранение: {save_name}"
                            })
                            
                            async with httpx.AsyncClient() as client:
                                upload_link_response = await client.get(
                                    "https://cloud-api.yandex.net/v1/disk/resources/upload",
                                    params={"path": save_path, "overwrite": "true"},
                                    headers={"Authorization": f"OAuth {token}"},
                                    timeout=30.0
                                )
                                
                                if upload_link_response.status_code != 200:
                                    raise Exception(f"Failed to get upload link: {upload_link_response.status_code}")
                                
                                upload_url = upload_link_response.json()["href"]
                                upload_response = await client.put(
                                    upload_url,
                                    content=white_bg_bytes,
                                    headers={"Content-Type": "image/png"},
                                    timeout=60.0
                                )
                                
                                if upload_response.status_code not in [201, 202]:
                                    raise Exception(f"Failed to upload file: {upload_response.status_code}")
                            
                            folder_results["files_processed"] += 1
                            logger.info(f"    Saved: {save_name}")
                            
                            yield await send_progress_update({
                                "type": "file_complete",
                                "folder_name": folder_name,
                                "file_name": file_name,
                                "saved_name": save_name,
                                "message": f"✓ Файл обработан и сохранен: {save_name}"
                            })
                            
                            # Для первой фотографии создаем версию с дизайном
                            if file_idx == 0:
                                try:
                                    # Получаем путь к фону
                                    background_paths = [
                                        "/app/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg",
                                        os.path.expanduser("~/background_remover/background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg"),
                                        "./background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg",
                                        "background/ФМГ_Авито_Универсальная_Обложка_Без_Товара.jpeg"
                                    ]
                                    
                                    background_path = None
                                    for path in background_paths:
                                        if os.path.exists(path):
                                            background_path = path
                                            break
                                    
                                    if background_path:
                                        with open(background_path, 'rb') as f:
                                            background_bytes = f.read()
                                        
                                        processed_file_obj = io.BytesIO(processed_bytes)
                                        processed_file_obj.name = "processed.png"
                                        background_file_obj = io.BytesIO(background_bytes)
                                        background_file_obj.name = "background.jpeg"
                                        
                                        os.environ["REPLICATE_API_TOKEN"] = api_key
                                        
                                        default_prompt = """Add the product from @img2 to the image @img1. The product must levitate directly above the podium, barely touching the podium surface, with a visible contact shadow."""
                                        
                                        processed_file_obj.seek(0)
                                        background_file_obj.seek(0)
                                        
                                        model_input = {
                                            "images": [background_file_obj, processed_file_obj],
                                            "prompt": default_prompt,
                                            "aspect_ratio": "4:3"
                                        }
                                        
                                        yield await send_progress_update({
                                            "type": "design_start",
                                            "folder_name": folder_name,
                                            "file_name": file_name,
                                            "message": f"Создание дизайна для: {file_name}"
                                        })
                                        
                                        design_output = await asyncio.to_thread(
                                            replicate.run,
                                            "prunaai/p-image-edit",
                                            input=model_input
                                        )
                                        
                                        p_image_edit_count += 1
                                        
                                        design_bytes = None
                                        if hasattr(design_output, 'read'):
                                            design_bytes = design_output.read()
                                        elif isinstance(design_output, str):
                                            async with httpx.AsyncClient() as http_client:
                                                response = await http_client.get(design_output, timeout=60.0)
                                                if response.status_code == 200:
                                                    design_bytes = response.content
                                        elif isinstance(design_output, list) and len(design_output) > 0:
                                            first_item = design_output[0]
                                            if hasattr(first_item, 'read'):
                                                design_bytes = first_item.read()
                                            elif isinstance(first_item, str):
                                                async with httpx.AsyncClient() as http_client:
                                                    response = await http_client.get(first_item, timeout=60.0)
                                                    if response.status_code == 200:
                                                        design_bytes = response.content
                                        
                                        if design_bytes:
                                            # Сохраняем дизайн на Yandex Disk
                                            design_name = f"{file_name.rsplit('.', 1)[0]}_design.png"
                                            design_save_path = f"{output_path}/{design_name}"
                                            
                                            async with httpx.AsyncClient() as client:
                                                upload_link_response = await client.get(
                                                    "https://cloud-api.yandex.net/v1/disk/resources/upload",
                                                    params={"path": design_save_path, "overwrite": "true"},
                                                    headers={"Authorization": f"OAuth {token}"},
                                                    timeout=30.0
                                                )
                                                
                                                if upload_link_response.status_code == 200:
                                                    upload_url = upload_link_response.json()["href"]
                                                    upload_response = await client.put(
                                                        upload_url,
                                                        content=design_bytes,
                                                        headers={"Content-Type": "image/png"},
                                                        timeout=60.0
                                                    )
                                                    
                                                    if upload_response.status_code in [201, 202]:
                                                        folder_results["design_created"] = True
                                                        logger.info(f"    Saved design: {design_name}")
                                                        
                                                        yield await send_progress_update({
                                                            "type": "design_complete",
                                                            "folder_name": folder_name,
                                                            "file_name": file_name,
                                                            "design_name": design_name,
                                                            "message": f"✓ Дизайн создан и сохранен: {design_name}"
                                                        })
                                
                                except Exception as e:
                                    logger.warning(f"    Failed to create design for {file_name}: {str(e)}")
                                    folder_results["errors"].append(f"Design creation failed: {str(e)}")
                        
                        except Exception as e:
                            logger.error(f"    Error processing {file_info.get('name', 'unknown')}: {str(e)}")
                            folder_results["errors"].append(f"{file_info.get('name', 'unknown')}: {str(e)}")
                            continue
                    
                    results.append(folder_results)
                    cost_logger.info(f"Папка {folder_name}: обработано {folder_results['files_processed']} файлов, дизайн: {'да' if folder_results['design_created'] else 'нет'}")
                    
                    yield await send_progress_update({
                        "type": "folder_complete",
                        "folder_name": folder_name,
                        "folder_index": folder_idx,
                        "files_processed": folder_results["files_processed"],
                        "design_created": folder_results["design_created"],
                        "message": f"✓ Папка {folder_name} обработана: {folder_results['files_processed']} файлов"
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing folder {folder_name}: {str(e)}")
                    results.append({
                        "folder_name": folder_name,
                        "folder_path": folder_path,
                        "files_processed": 0,
                        "design_created": False,
                        "errors": [str(e)]
                    })
                    
                    yield await send_progress_update({
                        "type": "folder_error",
                        "folder_name": folder_name,
                        "error": str(e),
                        "message": f"✗ Ошибка обработки папки {folder_name}: {str(e)}"
                    })
                    continue
            
            # Рассчитываем стоимость
            total_cost = (background_removal_count * COST_BACKGROUND_REMOVAL) + (p_image_edit_count * COST_P_IMAGE_EDIT)
            
            # Логируем итоговую стоимость
            cost_logger.info(f"=== Итоговая стоимость обработки ===")
            cost_logger.info(f"Background removal (удаление фона): {background_removal_count} изображений × ${COST_BACKGROUND_REMOVAL:.6f} = ${background_removal_count * COST_BACKGROUND_REMOVAL:.2f}")
            cost_logger.info(f"prunaai/p-image-edit (дизайн): {p_image_edit_count} изображений × ${COST_P_IMAGE_EDIT:.2f} = ${p_image_edit_count * COST_P_IMAGE_EDIT:.2f}")
            cost_logger.info(f"ОБЩАЯ СТОИМОСТЬ: ${total_cost:.2f}")
            cost_logger.info(f"=== Конец обработки ===\n")
            
            # Отправляем финальный результат
            yield await send_progress_update({
                "type": "complete",
                "success": True,
                "folders_processed": len(results),
                "total_background_removal": background_removal_count,
                "total_design_created": p_image_edit_count,
                "total_cost": round(total_cost, 2),
                "cost_breakdown": {
                    "background_removal": {
                        "count": background_removal_count,
                        "cost_per_image": COST_BACKGROUND_REMOVAL,
                        "total": round(background_removal_count * COST_BACKGROUND_REMOVAL, 2)
                    },
                    "p_image_edit": {
                        "count": p_image_edit_count,
                        "cost_per_image": COST_P_IMAGE_EDIT,
                        "total": round(p_image_edit_count * COST_P_IMAGE_EDIT, 2)
                    }
                },
                "results": results,
                "message": f"Обработка завершена! Обработано {len(results)} папок. Стоимость: ${round(total_cost, 2)}"
            })
        
        return StreamingResponse(
            generate_progress(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
        
        # Рассчитываем стоимость
        total_cost = (background_removal_count * COST_BACKGROUND_REMOVAL) + (p_image_edit_count * COST_P_IMAGE_EDIT)
        
        # Логируем итоговую стоимость
        cost_logger.info(f"=== Итоговая стоимость обработки ===")
        cost_logger.info(f"Background removal (удаление фона): {background_removal_count} изображений × ${COST_BACKGROUND_REMOVAL:.6f} = ${background_removal_count * COST_BACKGROUND_REMOVAL:.2f}")
        cost_logger.info(f"prunaai/p-image-edit (дизайн): {p_image_edit_count} изображений × ${COST_P_IMAGE_EDIT:.2f} = ${p_image_edit_count * COST_P_IMAGE_EDIT:.2f}")
        cost_logger.info(f"ОБЩАЯ СТОИМОСТЬ: ${total_cost:.2f}")
        cost_logger.info(f"=== Конец обработки ===\n")
        
        return {
            "success": True,
            "folders_processed": len(results),
            "total_background_removal": background_removal_count,
            "total_design_created": p_image_edit_count,
            "total_cost": round(total_cost, 2),
            "cost_breakdown": {
                "background_removal": {
                    "count": background_removal_count,
                    "cost_per_image": COST_BACKGROUND_REMOVAL,
                    "total": round(background_removal_count * COST_BACKGROUND_REMOVAL, 2)
                },
                "p_image_edit": {
                    "count": p_image_edit_count,
                    "cost_per_image": COST_P_IMAGE_EDIT,
                    "total": round(p_image_edit_count * COST_P_IMAGE_EDIT, 2)
                }
            },
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch folder processing: {str(e)}", exc_info=True)
        cost_logger.error(f"ОШИБКА обработки: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch folder processing error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # Railway и другие платформы устанавливают PORT через переменную окружения
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

