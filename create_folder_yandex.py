#!/usr/bin/env python3
"""
Скрипт для создания папки на Яндекс Диске
Создает папку "dupa" в указанной папке
"""

import os
import re
import sys
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def create_folder_in_yandex(url, folder_name="dupa"):
    """
    Создает папку на Яндекс Диске
    
    Args:
        url: URL публичной папки (например: https://disk.yandex.ru/d/-uXMLsCHrFtxzg)
        folder_name: Название создаваемой папки (по умолчанию "dupa")
    """
    token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        print("❌ Ошибка: YANDEX_DISK_TOKEN не найден в .env файле")
        print("   Установите токен в файле .env или в переменных окружения")
        return False
    
    print("=" * 60)
    print("Создание папки на Яндекс Диске")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Название папки: {folder_name}\n")
    
    # Извлекаем ID из URL
    match = re.search(r'/d/([^/?]+)', url)
    if not match:
        print("❌ Ошибка: Неверный формат URL")
        print("   Ожидается формат: https://disk.yandex.ru/d/ID")
        return False
    
    folder_id = match.group(1)
    print(f"📁 ID папки: {folder_id}\n")
    
    async with httpx.AsyncClient() as client:
        try:
            # Сначала пробуем получить информацию о публичной папке
            print("🔍 Получение информации о папке...")
            public_response = await client.get(
                "https://cloud-api.yandex.net/v1/disk/public/resources",
                params={"public_key": folder_id, "limit": 1},
                headers={"Authorization": f"OAuth {token}"},
                timeout=30.0
            )
            
            if public_response.status_code == 200:
                public_data = public_response.json()
                public_path = public_data.get("path", "")
                print(f"✅ Публичная папка найдена")
                print(f"   Путь: {public_path}")
                
                # Пробуем создать папку напрямую в публичной папке (если это наша папка)
                target_path_direct = f"{public_path}/{folder_name}"
                print(f"\n📂 Попытка создания папки напрямую в публичной папке...")
                print(f"   Путь: {target_path_direct}")
                
                create_response = await client.put(
                    "https://cloud-api.yandex.net/v1/disk/resources",
                    params={"path": target_path_direct},
                    headers={"Authorization": f"OAuth {token}"},
                    timeout=30.0
                )
                
                if create_response.status_code in [201, 202]:
                    print(f"✅ Папка '{folder_name}' успешно создана в публичной папке!")
                    print(f"   Путь: {target_path_direct}")
                    return True
                elif create_response.status_code == 409:
                    print(f"⚠️  Папка '{folder_name}' уже существует")
                    print(f"   Путь: {target_path_direct}")
                    return True
                elif create_response.status_code == 403:
                    # Нет доступа к публичной папке, создаем в своей папке
                    print(f"⚠️  Нет доступа для создания папки в публичной папке")
                    print(f"   Создаем папку в корневой папке пользователя...")
                    
                    target_path = f"/{folder_name}"
                    create_response = await client.put(
                        "https://cloud-api.yandex.net/v1/disk/resources",
                        params={"path": target_path},
                        headers={"Authorization": f"OAuth {token}"},
                        timeout=30.0
                    )
                    
                    if create_response.status_code in [201, 202]:
                        print(f"✅ Папка '{folder_name}' успешно создана в корне!")
                        print(f"   Путь: {target_path}")
                        return True
                    elif create_response.status_code == 409:
                        print(f"⚠️  Папка '{folder_name}' уже существует в корне")
                        print(f"   Путь: {target_path}")
                        return True
                    else:
                        error_text = create_response.text
                        print(f"❌ Ошибка: {create_response.status_code}")
                        print(f"   Ответ: {error_text}")
                        return False
                else:
                    error_text = create_response.text
                    print(f"⚠️  Не удалось создать в публичной папке: {create_response.status_code}")
                    print(f"   Пробуем создать в корневой папке...")
                    
                    # Fallback: создаем в корне
                    target_path = f"/{folder_name}"
                    create_response = await client.put(
                        "https://cloud-api.yandex.net/v1/disk/resources",
                        params={"path": target_path},
                        headers={"Authorization": f"OAuth {token}"},
                        timeout=30.0
                    )
                    
                    if create_response.status_code in [201, 202]:
                        print(f"✅ Папка '{folder_name}' успешно создана в корне!")
                        print(f"   Путь: {target_path}")
                        return True
                    elif create_response.status_code == 409:
                        print(f"⚠️  Папка '{folder_name}' уже существует")
                        print(f"   Путь: {target_path}")
                        return True
                    else:
                        print(f"❌ Ошибка: {create_response.status_code}")
                        print(f"   Ответ: {create_response.text}")
                        return False
                    
            elif public_response.status_code == 404:
                # Публичная папка не найдена через API, пробуем создать в корне
                print("⚠️  Публичная папка не найдена через API")
                print("   Пробуем создать папку в корневой папке...")
                
                # Создаем папку напрямую в корне
                target_path = f"/{folder_name}"
                
                create_response = await client.put(
                    "https://cloud-api.yandex.net/v1/disk/resources",
                    params={"path": target_path},
                    headers={"Authorization": f"OAuth {token}"},
                    timeout=30.0
                )
                
                if create_response.status_code in [201, 202]:
                    print(f"✅ Папка '{folder_name}' успешно создана в корне!")
                    print(f"   Путь: {target_path}")
                    return True
                elif create_response.status_code == 409:
                    print(f"⚠️  Папка '{folder_name}' уже существует в корне")
                    print(f"   Путь: {target_path}")
                    return True
                else:
                    error_text = create_response.text
                    print(f"❌ Ошибка при создании папки: {create_response.status_code}")
                    print(f"   Ответ: {error_text}")
                    return False
            else:
                print(f"❌ Ошибка при получении информации о папке: {public_response.status_code}")
                print(f"   Ответ: {public_response.text}")
                
                # Пробуем создать папку в корне в любом случае
                print("\n📂 Пробуем создать папку в корневой папке...")
                target_path = f"/{folder_name}"
                
                create_response = await client.put(
                    "https://cloud-api.yandex.net/v1/disk/resources",
                    params={"path": target_path},
                    headers={"Authorization": f"OAuth {token}"},
                    timeout=30.0
                )
                
                if create_response.status_code in [201, 202]:
                    print(f"✅ Папка '{folder_name}' успешно создана!")
                    print(f"   Путь: {target_path}")
                    return True
                elif create_response.status_code == 409:
                    print(f"⚠️  Папка '{folder_name}' уже существует")
                    print(f"   Путь: {target_path}")
                    return True
                else:
                    error_text = create_response.text
                    print(f"❌ Ошибка: {create_response.status_code}")
                    print(f"   Ответ: {error_text}")
                    return False
                    
        except httpx.RequestError as e:
            print(f"❌ Ошибка сети: {str(e)}")
            return False
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

def main():
    url = "https://disk.yandex.ru/d/-uXMLsCHrFtxzg"
    folder_name = "dupa"
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    if len(sys.argv) > 2:
        folder_name = sys.argv[2]
    
    success = asyncio.run(create_folder_in_yandex(url, folder_name))
    
    print("\n" + "=" * 60)
    if success:
        print("✅ Готово!")
    else:
        print("❌ Завершено с ошибками")
    print("=" * 60)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

