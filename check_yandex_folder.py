#!/usr/bin/env python3
"""
Скрипт для проверки информации о публичной папке Яндекс Диска
Показывает информацию о владельце папки и её содержимом
"""

import os
import re
import sys
import httpx
import json
from urllib.parse import unquote
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

def extract_folder_id(url):
    """Извлекает ID папки из URL"""
    match = re.search(r'/d/([^/?]+)', url)
    if match:
        return match.group(1)
    return None

def get_folder_info_via_api(folder_id, token=None):
    """Получает информацию о папке через API Яндекс Диска"""
    if not token:
        token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not token:
        return None, "Токен не найден. Установите YANDEX_DISK_TOKEN в переменных окружения."
    
    try:
        async def fetch_info():
            async with httpx.AsyncClient() as client:
                # Пробуем получить информацию через public API
                response = await client.get(
                    "https://cloud-api.yandex.net/v1/disk/public/resources",
                    params={"public_key": folder_id, "limit": 1000},
                    headers={"Authorization": f"OAuth {token}"},
                    timeout=30.0
                )
                return response
        
        import asyncio
        response = asyncio.run(fetch_info())
        
        if response.status_code == 200:
            data = response.json()
            return data, None
        else:
            return None, f"API вернул статус {response.status_code}: {response.text}"
    except Exception as e:
        return None, f"Ошибка при запросе к API: {str(e)}"

def get_folder_info_via_html(url):
    """Получает информацию о папке через парсинг HTML страницы"""
    try:
        async def fetch_html():
            async with httpx.AsyncClient() as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
                }
                response = await client.get(url, headers=headers, timeout=30.0, follow_redirects=True)
                return response
        
        import asyncio
        response = asyncio.run(fetch_html())
        
        if response.status_code != 200:
            return None, f"Не удалось загрузить страницу: {response.status_code}"
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        info = {
            "folder_name": None,
            "owner": None,
            "owner_login": None,
            "created_date": None,
            "total_files": 0,
            "folders": [],
            "has_captcha": False,
            "raw_html_length": len(html)
        }
        
        # Проверяем наличие CAPTCHA
        if "робот" in html.lower() or "captcha" in html.lower() or "smartcaptcha" in html.lower():
            info["has_captcha"] = True
            print("   ⚠️  Обнаружена CAPTCHA на странице")
        
        # Ищем название папки
        title = soup.find('title')
        if title:
            title_text = title.get_text(strip=True)
            info["folder_name"] = title_text
            # Если это CAPTCHA, название будет "Вы не робот?" или подобное
            if "робот" in title_text.lower():
                info["has_captcha"] = True
        
        # Ищем информацию о владельце
        # Яндекс Диск обычно показывает владельца в мета-тегах или в структурированных данных
        meta_owner = soup.find('meta', attrs={'property': 'og:site_name'}) or soup.find('meta', attrs={'name': 'author'})
        if meta_owner:
            info["owner"] = meta_owner.get('content', '')
        
        # Ищем в JSON-LD или других структурированных данных
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if 'author' in data:
                        info["owner"] = data.get('author', {}).get('name', '')
            except:
                pass
        
        # Ищем информацию в тексте страницы
        # Обычно Яндекс Диск показывает "Папка пользователя [имя]" или подобное
        page_text = soup.get_text()
        
        # Ищем паттерны типа "Папка пользователя", "Владелец" и т.д.
        owner_patterns = [
            r'Папка пользователя\s+([^\n\r]+)',
            r'Владелец[:\s]+([^\n\r]+)',
            r'Автор[:\s]+([^\n\r]+)',
            r'Пользователь[:\s]+([^\n\r]+)',
            r'([А-Яа-яA-Za-z0-9_\-\.]+)\s+—\s+Яндекс\s+Диск',  # Имя пользователя перед "— Яндекс Диск"
        ]
        
        for pattern in owner_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                owner_name = match.group(1).strip()
                # Фильтруем слишком короткие или нерелевантные совпадения
                if len(owner_name) > 2 and owner_name not in ['Яндекс', 'Диск', 'Папка']:
                    info["owner"] = owner_name
                    break
        
        # Ищем в мета-тегах Open Graph
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        if og_title:
            og_title_content = og_title.get('content', '')
            # Обычно формат: "Название папки — Яндекс Диск" или "Папка пользователя Имя"
            if '—' in og_title_content:
                parts = og_title_content.split('—')
                if len(parts) > 0:
                    potential_name = parts[0].strip()
                    if potential_name and len(potential_name) > 2:
                        info["folder_name"] = potential_name
            elif 'пользователя' in og_title_content.lower():
                match = re.search(r'пользователя\s+([^\s]+)', og_title_content, re.IGNORECASE)
                if match:
                    info["owner"] = match.group(1).strip()
        
        # Ищем в структурированных данных (JSON-LD)
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if script.string:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if 'author' in data:
                            author = data['author']
                            if isinstance(author, dict):
                                info["owner"] = author.get('name', '')
                            elif isinstance(author, str):
                                info["owner"] = author
                        if 'name' in data and not info["folder_name"]:
                            info["folder_name"] = data.get('name', '')
            except:
                pass
        
        # Ищем в data-атрибутах
        elements_with_data = soup.find_all(attrs={'data-user': True})
        for elem in elements_with_data:
            user_data = elem.get('data-user')
            if user_data:
                try:
                    user_info = json.loads(user_data)
                    if isinstance(user_info, dict):
                        info["owner"] = user_info.get('name') or user_info.get('displayName') or user_info.get('login', '')
                        info["owner_login"] = user_info.get('login', '')
                except:
                    info["owner"] = user_data
        
        # Подсчитываем файлы и папки
        links = soup.find_all('a', href=True)
        folders_found = set()
        files_count = 0
        
        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Ищем папки (обычно имеют префикс + или специальный класс)
            if '+' in text or 'folder' in href.lower() or 'dir' in href.lower():
                folder_name = text.replace('+', '').strip()
                if folder_name and folder_name not in folders_found:
                    folders_found.add(folder_name)
                    info["folders"].append(folder_name)
            
            # Подсчитываем файлы
            if any(ext in text.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.doc']):
                files_count += 1
        
        info["total_files"] = files_count
        
        # Ищем дату создания (если есть)
        date_patterns = [
            r'(\d{2}\.\d{2}\.\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, page_text)
            if match:
                info["created_date"] = match.group(1)
                break
        
        return info, None
        
    except Exception as e:
        return None, f"Ошибка при парсинге HTML: {str(e)}"

def main():
    url = "https://disk.yandex.ru/d/kXWj5qy7vdZwXA"
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    
    print("=" * 60)
    print("Проверка информации о папке Яндекс Диска")
    print("=" * 60)
    print(f"URL: {url}\n")
    
    folder_id = extract_folder_id(url)
    if not folder_id:
        print("❌ Ошибка: Не удалось извлечь ID папки из URL")
        print("Ожидается формат: https://disk.yandex.ru/d/ID")
        sys.exit(1)
    
    print(f"📁 ID папки: {folder_id}\n")
    
    # Пробуем получить информацию через API
    print("🔍 Попытка получения информации через API...")
    api_data, api_error = get_folder_info_via_api(folder_id)
    
    if api_data:
        print("✅ Информация получена через API:")
        print(f"   Название: {api_data.get('name', 'Не указано')}")
        print(f"   Путь: {api_data.get('path', 'Не указано')}")
        print(f"   Тип: {api_data.get('type', 'Не указано')}")
        print(f"   Размер: {api_data.get('size', 0)} байт")
        
        if 'created' in api_data:
            print(f"   Создано: {api_data['created']}")
        if 'modified' in api_data:
            print(f"   Изменено: {api_data['modified']}")
        
        # Информация о владельце (если есть в ответе)
        if 'owner' in api_data:
            owner = api_data['owner']
            print(f"   Владелец: {owner.get('display_name', owner.get('login', 'Не указано'))}")
            print(f"   Логин: {owner.get('login', 'Не указано')}")
        
        # Список элементов
        items = api_data.get('_embedded', {}).get('items', [])
        if items:
            print(f"\n   Содержимое ({len(items)} элементов):")
            folders = [item for item in items if item.get('type') == 'dir']
            files = [item for item in items if item.get('type') == 'file']
            print(f"   - Папок: {len(folders)}")
            print(f"   - Файлов: {len(files)}")
            
            if folders:
                print("\n   Папки:")
                for folder in folders[:10]:  # Показываем первые 10
                    print(f"     📁 {folder.get('name', 'Без имени')}")
    else:
        print(f"⚠️  API недоступен: {api_error}")
    
    print("\n" + "-" * 60)
    print("🔍 Попытка получения информации через парсинг HTML...")
    
    # Пробуем получить информацию через парсинг HTML
    html_info, html_error = get_folder_info_via_html(url)
    
    if html_info:
        print("✅ Информация получена через HTML:")
        
        if html_info.get("has_captcha"):
            print("   ⚠️  ВНИМАНИЕ: На странице обнаружена CAPTCHA!")
            print("   Это означает, что Яндекс блокирует автоматический доступ.")
            print("   Для полной информации откройте URL в браузере вручную.\n")
        
        if html_info.get("folder_name") and not html_info.get("has_captcha"):
            print(f"   Название: {html_info['folder_name']}")
        elif html_info.get("folder_name"):
            print(f"   Название (возможно неточное из-за CAPTCHA): {html_info['folder_name']}")
        
        if html_info.get("owner"):
            print(f"   Владелец: {html_info['owner']}")
        if html_info.get("owner_login"):
            print(f"   Логин: {html_info['owner_login']}")
        if html_info.get("created_date"):
            print(f"   Дата создания: {html_info['created_date']}")
        
        if not html_info.get("has_captcha"):
            if html_info.get("folders"):
                print(f"\n   Найдено папок: {len(html_info['folders'])}")
                for folder in html_info['folders'][:10]:  # Показываем первые 10
                    print(f"     📁 {folder}")
            if html_info.get("total_files") > 0:
                print(f"   Найдено файлов: {html_info['total_files']}")
        
        print(f"\n   Дополнительная информация:")
        print(f"   Размер HTML: {html_info.get('raw_html_length', 0)} байт")
        
    else:
        print(f"⚠️  HTML парсинг не удался: {html_error}")
    
    print("\n" + "=" * 60)
    
    # Рекомендации
    if html_info and html_info.get("has_captcha"):
        print("\n💡 РЕКОМЕНДАЦИИ:")
        print("   Яндекс блокирует автоматический доступ к этой папке через CAPTCHA.")
        print("   Для получения полной информации:")
        print("   1. Откройте URL в браузере вручную")
        print("   2. Пройдите проверку CAPTCHA")
        print("   3. На странице вы увидите:")
        print("      - Название папки")
        print("      - Имя владельца (обычно вверху страницы)")
        print("      - Список папок и файлов")
        print("\n   Альтернативно:")
        print("   - Если у вас есть YANDEX_DISK_TOKEN владельца папки,")
        print("     вы можете использовать API для доступа")
        print("   - Или попросите владельца предоставить доступ к папке")
    
    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)

if __name__ == "__main__":
    main()

