"""
Skrypt do sprawdzania folderów na Yandex Disk
"""
import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()


async def list_folder_recursive(client, token, path, depth=0, max_depth=10):
    """Rekurencyjnie listuje foldery i subfoldery"""
    if depth > max_depth:
        return []
    
    try:
        response = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources",
            params={"path": path, "limit": 1000},
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        items = data.get("_embedded", {}).get("items", [])
        
        folders = []
        indent = "  " * depth
        
        for item in items:
            item_type = item.get("type")
            name = item.get("name")
            item_path = item.get("path", path)
            
            if item_type == "dir":
                folders.append({"name": name, "path": item_path, "depth": depth})
                print(f"{indent}📁 {name}")
                
                # Rekurencyjnie przeszukaj subfoldery
                subfolders = await list_folder_recursive(client, token, item_path, depth + 1, max_depth)
                folders.extend(subfolders)
            else:
                # Pliki też pokazujemy, ale z innym symbolem
                print(f"{indent}📄 {name} ({item_type})")
        
        return folders
        
    except Exception as e:
        print(f"{'  ' * depth}❌ Błąd przy przeszukiwaniu {path}: {e}")
        return []


async def get_yandex_disk_info(client, token):
    """Pobiera informacje o koncie Yandex Disk"""
    try:
        response = await client.get(
            "https://cloud-api.yandex.net/v1/disk",
            headers={"Authorization": f"OAuth {token}"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                "login": data.get("user", {}).get("login", "Nieznany"),
                "display_name": data.get("user", {}).get("display_name", "Nieznany"),
                "uid": data.get("user", {}).get("uid", "Nieznany"),
                "total_space": data.get("total_space", 0),
                "used_space": data.get("used_space", 0),
                "trash_size": data.get("trash_size", 0),
            }
        else:
            return None
    except Exception as e:
        print(f"Błąd przy pobieraniu informacji o koncie: {e}")
        return None


async def list_yandex_folders():
    """Lista wszystkich folderów i subfolderów na Yandex Disk"""
    yandex_token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not yandex_token:
        print("BŁĄD: YANDEX_DISK_TOKEN nie jest ustawiony")
        return
    
    async with httpx.AsyncClient() as client:
        try:
            # Najpierw pobieramy informacje o koncie
            print("\n" + "="*70)
            print("INFORMACJE O KONCIE YANDEX DISK")
            print("="*70)
            
            account_info = await get_yandex_disk_info(client, yandex_token)
            if account_info:
                print(f"Login (Email): {account_info['login']}")
                print(f"Nazwa wyświetlana: {account_info['display_name']}")
                print(f"UID: {account_info['uid']}")
                total_gb = account_info['total_space'] / (1024**3) if account_info['total_space'] else 0
                used_gb = account_info['used_space'] / (1024**3) if account_info['used_space'] else 0
                print(f"Całkowita przestrzeń: {total_gb:.2f} GB")
                print(f"Użyta przestrzeń: {used_gb:.2f} GB")
                print(f"Wolne miejsce: {total_gb - used_gb:.2f} GB")
            else:
                print("❌ Nie udało się pobrać informacji o koncie")
            
            print("\n" + "="*70)
            print("STRUKTURA FOLDERÓW NA YANDEX DISK")
            print("="*70 + "\n")
            
            # Listujemy rekurencyjnie wszystkie foldery
            all_folders = await list_folder_recursive(client, yandex_token, "/", depth=0, max_depth=10)
            
            print("\n" + "="*70)
            print("PODSUMOWANIE")
            print("="*70)
            print(f"Łącznie folderów: {len(all_folders)}")
            
            # Sprawdzamy czy istnieją konkretne foldery
            print("\n" + "="*70)
            print("SPRAWDZANIE KONKRETNYCH FOLDERÓW: Дизайн i КомТех")
            print("="*70)
            
            check_folders = ["Дизайн", "КомТех"]
            for folder_name in check_folders:
                # Sprawdzamy na głównym poziomie
                check_response = await client.get(
                    "https://cloud-api.yandex.net/v1/disk/resources",
                    params={"path": f"/{folder_name}"},
                    headers={"Authorization": f"OAuth {yandex_token}"},
                    timeout=30.0
                )
                
                if check_response.status_code == 200:
                    folder_info = check_response.json()
                    if folder_info.get("type") == "dir":
                        print(f"✅ Folder '{folder_name}' ISTNIEJE na głównym poziomie")
                        print(f"   Ścieżka: {folder_info.get('path')}")
                    else:
                        print(f"❌ '{folder_name}' istnieje, ale to nie jest folder (typ: {folder_info.get('type')})")
                else:
                    # Sprawdzamy czy może jest w jakimś subfolderze
                    found = False
                    for folder in all_folders:
                        if folder["name"] == folder_name:
                            print(f"✅ Folder '{folder_name}' ZNALEZIONY w strukturze")
                            print(f"   Ścieżka: {folder['path']}")
                            print(f"   Poziom zagnieżdżenia: {folder['depth']}")
                            found = True
                            break
                    
                    if not found:
                        print(f"❌ Folder '{folder_name}' NIE ZNALEZIONY w strukturze folderów")
            
            print("="*70 + "\n")
            
        except httpx.HTTPError as e:
            print(f"Błąd HTTP: {e}")
        except Exception as e:
            print(f"Nieoczekiwany błąd: {e}")


if __name__ == "__main__":
    asyncio.run(list_yandex_folders())





