"""
Skrypt do utworzenia folderu "pasha" na Yandex Disk i sprawdzenia czy się utworzył
"""
import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()


async def create_and_verify_folder():
    """Tworzy folder pasha na Yandex Disk i weryfikuje jego istnienie"""
    yandex_token = os.getenv("YANDEX_DISK_TOKEN")
    
    if not yandex_token:
        print("❌ BŁĄD: YANDEX_DISK_TOKEN nie jest ustawiony w .env")
        print("Ustaw zmienną środowiskową YANDEX_DISK_TOKEN z twoim access tokenem OAuth")
        return
    
    folder_name = "pasha"
    folder_path = f"/{folder_name}"
    
    async with httpx.AsyncClient() as client:
        try:
            print("\n" + "="*70)
            print("TWORZENIE FOLDERU 'pasha' NA YANDEX DISK")
            print("="*70)
            
            # 1. Próbujemy utworzyć folder
            print(f"\n1. Tworzenie folderu: {folder_path}")
            response = await client.put(
                "https://cloud-api.yandex.net/v1/disk/resources",
                params={"path": folder_path},
                headers={"Authorization": f"OAuth {yandex_token}"},
                timeout=30.0
            )
            
            if response.status_code in [201, 202]:
                print(f"✅ Folder '{folder_name}' został UTWORZONY pomyślnie!")
            elif response.status_code == 409:
                print(f"ℹ️  Folder '{folder_name}' JUŻ ISTNIEJE (to w porządku)")
            else:
                print(f"❌ BŁĄD przy tworzeniu folderu. Status: {response.status_code}")
                print(f"Odpowiedź: {response.text}")
                return
            
            # 2. Weryfikujemy że folder istnieje
            print(f"\n2. Weryfikacja istnienia folderu: {folder_path}")
            check_response = await client.get(
                "https://cloud-api.yandex.net/v1/disk/resources",
                params={"path": folder_path},
                headers={"Authorization": f"OAuth {yandex_token}"},
                timeout=30.0
            )
            
            if check_response.status_code == 200:
                folder_info = check_response.json()
                
                if folder_info.get("type") == "dir":
                    print(f"✅ WERYFIKACJA: Folder '{folder_name}' ISTNIEJE i jest katalogiem")
                    print(f"   Ścieżka: {folder_info.get('path')}")
                    print(f"   Nazwa: {folder_info.get('name')}")
                    print(f"   Typ: {folder_info.get('type')}")
                    print(f"   Data utworzenia: {folder_info.get('created', 'Nieznana')}")
                    print(f"   Data modyfikacji: {folder_info.get('modified', 'Nieznana')}")
                    
                    # 3. Sprawdzamy listę folderów na głównym poziomie
                    print(f"\n3. Lista folderów na głównym poziomie:")
                    list_response = await client.get(
                        "https://cloud-api.yandex.net/v1/disk/resources",
                        params={"path": "/", "limit": 1000},
                        headers={"Authorization": f"OAuth {yandex_token}"},
                        timeout=30.0
                    )
                    
                    if list_response.status_code == 200:
                        list_data = list_response.json()
                        items = list_data.get("_embedded", {}).get("items", [])
                        
                        folders = [item for item in items if item.get("type") == "dir"]
                        print(f"   Znaleziono {len(folders)} folderów:")
                        
                        found = False
                        for folder in folders:
                            if folder.get("name") == folder_name:
                                print(f"   ✅ {folder.get('name')} - ISTNIEJE!")
                                found = True
                            else:
                                print(f"   📁 {folder.get('name')}")
                        
                        if not found:
                            print(f"   ❌ Folder '{folder_name}' NIE ZNALEZIONY na liście!")
                    else:
                        print(f"   ❌ Nie udało się pobrać listy folderów")
                    
                else:
                    print(f"❌ '{folder_name}' istnieje, ale to NIE jest folder (typ: {folder_info.get('type')})")
            else:
                print(f"❌ Folder '{folder_name}' NIE ISTNIEJE po utworzeniu!")
                print(f"   Status: {check_response.status_code}")
            
            print("\n" + "="*70 + "\n")
            
        except httpx.HTTPError as e:
            print(f"❌ Błąd HTTP: {e}")
        except Exception as e:
            print(f"❌ Nieoczekiwany błąd: {e}")


if __name__ == "__main__":
    asyncio.run(create_and_verify_folder())



