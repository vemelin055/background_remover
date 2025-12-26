import os
import io
import asyncio
import re
import json
import logging
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse, FileResponse
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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

async def process_replicate(image_bytes: bytes, api_key: str) -> bytes:
    """Replicate API используя 851-labs/background-remover"""
    # Используем REPLICATE_API_KEY из .env если не передан ключ
    if not api_key:
        api_key = os.getenv("REPLICATE_API_KEY", "")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="Replicate API key not provided")
    
    # Устанавливаем API ключ для replicate
    os.environ["REPLICATE_API_TOKEN"] = api_key
    
    try:
        # Загружаем изображение в replicate storage через files.upload()
        # Это возвращает объект с URL, который можно использовать в input
        file = replicate.files.upload(content=image_bytes)
        image_url = file.url if hasattr(file, 'url') else str(file)
        
        # Используем replicate.run с новым моделью и URL изображения
        output = replicate.run(
            "851-labs/background-remover:a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc",
            input={"image": image_url}
        )
        
        # output может быть файловым объектом или URL
        if hasattr(output, 'read'):
            # Если это файловый объект
            result_bytes = output.read()
        elif hasattr(output, 'url'):
            # Если это объект с URL
            async with httpx.AsyncClient() as client:
                response = await client.get(output.url, timeout=60.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail=f"Failed to download Replicate result: {response.status_code}")
                result_bytes = response.content
        elif isinstance(output, str):
            # Если это строка URL
            async with httpx.AsyncClient() as client:
                response = await client.get(output, timeout=60.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail=f"Failed to download Replicate result: {response.status_code}")
                result_bytes = response.content
        else:
            raise HTTPException(status_code=500, detail=f"Unexpected Replicate output format: {type(output)}")
        
        return result_bytes
                
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Replicate processing error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Replicate processing error: {str(e)}")

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
    
    return env_keys.get(model) or ""

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
        
        # fal-ai/imageutils/rembg не требует prompt, но принимает его для совместимости
        processed_bytes = await MODELS[model](image_bytes, api_key, prompt)
        
        return Response(
            content=processed_bytes,
            media_type="image/png"
        )
    except HTTPException:
        raise
    except Exception as e:
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
        
        # Масштабируем изображение так, чтобы оно заполнило шаблон
        # Используем больший масштаб, чтобы изображение покрывало большую часть/всё белое поле
        # Вычисляем масштаб для заполнения по ширине и высоте, выбираем больший
        scale_width = template_width / img_width
        scale_height = template_height / img_height
        
        # Используем больший масштаб, чтобы изображение заполнило шаблон
        # Это гарантирует, что изображение покроет всё белое поле
        scale = max(scale_width, scale_height)
        
        # Масштабируем изображение
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        processed_img = processed_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Центрируем (если изображение больше шаблона, оно будет обрезано по краям)
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
        # Формат: https://disk.yandex.ru/d/-uXMLsCHrFtxzg
        match = re.search(r'/d/([^/?]+)', public_url)
        if not match:
            raise HTTPException(status_code=400, detail="Invalid Yandex Disk URL")
        
        folder_id = match.group(1)
        logger.info(f"Parsing Yandex Disk folder: {folder_id}")
        
        # Парсим публичную страницу
        async with httpx.AsyncClient() as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
            }
            response = await client.get(
                f"https://disk.yandex.ru/d/{folder_id}",
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
                            file_url = f"https://disk.yandex.ru/d/{folder_id}/{href.split('?')[0]}"
                        
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
                            file_url = f"https://disk.yandex.ru/d/{folder_id}/{src.split('?')[0]}"
                        
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
                                                            file_url = f"https://disk.yandex.ru{file_url}" if file_url.startswith('/') else f"https://disk.yandex.ru/d/{folder_id}/{file_url}"
                                                        
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
                            href = f"https://disk.yandex.ru{href}" if href.startswith('/') else f"https://disk.yandex.ru/d/{folder_id}/{href}"
                        
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
                                href = f"https://disk.yandex.ru{href}" if href.startswith('/') else f"https://disk.yandex.ru/d/{folder_id}/{href}"
                            
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
            
            return {"files": files, "folder_id": folder_id, "total_found": len(files)}
            
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

if __name__ == "__main__":
    import uvicorn
    # Railway и другие платформы устанавливают PORT через переменную окружения
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

