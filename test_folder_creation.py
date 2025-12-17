"""
Testy tworzenia folderów.

UWAGA: Aby uruchomić testy, użyj:
    pytest test_folder_creation.py -v

NIE używaj: python test_folder_creation.py (to nie zadziała, ponieważ pytest musi uruchomić funkcje testowe)

Dla testu Yandex Disk potrzebujesz:
1. Ustaw zmienną środowiskową YANDEX_DISK_TOKEN z twoim access tokenem OAuth
2. Opcjonalnie: Ustaw YANDEX_DISK_TEST_PARENT_FOLDER (domyślnie "/" - główny katalog)
   Przykład: export YANDEX_DISK_TEST_PARENT_FOLDER="/КомТех"
"""

import os
import tempfile
import shutil
import pytest
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()


def test_can_create_folder_pasha():
    """Test sprawdzający czy można utworzyć folder o nazwie pasha"""
    folder_name = "pasha"
    
    # Używamy tymczasowego katalogu dla testu
    with tempfile.TemporaryDirectory() as temp_dir:
        test_folder_path = os.path.join(temp_dir, folder_name)
        
        # Tworzymy folder
        os.makedirs(test_folder_path)
        
        # Sprawdzamy czy folder istnieje
        assert os.path.exists(test_folder_path), f"Folder '{folder_name}' nie został utworzony"
        assert os.path.isdir(test_folder_path), f"'{folder_name}' nie jest katalogiem"
        
        # Sprawdzamy czy nazwa jest poprawna
        assert os.path.basename(test_folder_path) == folder_name, f"Nazwa folderu nie jest '{folder_name}'"


def test_can_create_folder_pasha_with_pathlib():
    """Test sprawdzający czy można utworzyć folder o nazwie pasha używając pathlib"""
    folder_name = "pasha"
    
    # Używamy tymczasowego katalogu dla testu
    with tempfile.TemporaryDirectory() as temp_dir:
        test_folder_path = Path(temp_dir) / folder_name
        
        # Tworzymy folder
        test_folder_path.mkdir()
        
        # Sprawdzamy czy folder istnieje
        assert test_folder_path.exists(), f"Folder '{folder_name}' nie został utworzony"
        assert test_folder_path.is_dir(), f"'{folder_name}' nie jest katalogiem"
        
        # Sprawdzamy czy nazwa jest poprawna
        assert test_folder_path.name == folder_name, f"Nazwa folderu nie jest '{folder_name}'"


def test_can_create_folder_pasha_in_current_directory():
    """Test sprawdzający czy można utworzyć folder pasha w bieżącym katalogu (z czyszczeniem)"""
    folder_name = "pasha"
    
    # Sprawdzamy czy folder już istnieje i usuwamy go jeśli tak
    if os.path.exists(folder_name):
        if os.path.isdir(folder_name):
            shutil.rmtree(folder_name)
        else:
            os.remove(folder_name)
    
    try:
        # Tworzymy folder
        os.makedirs(folder_name, exist_ok=True)
        
        # Sprawdzamy czy folder istnieje
        assert os.path.exists(folder_name), f"Folder '{folder_name}' nie został utworzony"
        assert os.path.isdir(folder_name), f"'{folder_name}' nie jest katalogiem"
        
    finally:
        # Czyścimy - usuwamy folder po teście
        if os.path.exists(folder_name):
            shutil.rmtree(folder_name)


@pytest.mark.asyncio
async def test_can_create_folder_pasha_on_yandex_disk():
    """Test sprawdzający czy można utworzyć folder o nazwie pasha na Yandex Disk"""
    folder_name = "pasha"
    
    # Pobieramy access token OAuth z zmiennej środowiskowej
    # Uwaga: To nie jest YANDEX_DISK_CLIENT_ID/CLIENT_SECRET, ale access token uzyskany po autoryzacji OAuth
    # Możesz uzyskać token przez aplikację (autoryzacja przez /auth/yandex) lub bezpośrednio przez OAuth flow
    yandex_token = os.getenv("YANDEX_DISK_TOKEN")
    
    # Pomijamy test jeśli token nie jest dostępny
    if not yandex_token:
        pytest.skip(
            "YANDEX_DISK_TOKEN nie jest ustawiony. "
            "To musi być access token OAuth (nie CLIENT_ID/CLIENT_SECRET). "
            "Uzyskaj token przez autoryzację OAuth i ustaw zmienną środowiskową YANDEX_DISK_TOKEN."
        )
    
    # Ścieżka folderu na Yandex Disk
    # Możesz zmienić parent_folder na konkretną ścieżkę, np. "/КомТех" jeśli chcesz utworzyć folder w folderze КомТех
    parent_folder = os.getenv("YANDEX_DISK_TEST_PARENT_FOLDER", "/")
    if parent_folder == "/":
        folder_path = f"/{folder_name}"
    else:
        # Upewniamy się że parent_folder zaczyna się od /
        if not parent_folder.startswith("/"):
            parent_folder = f"/{parent_folder}"
        folder_path = f"{parent_folder}/{folder_name}"
    
    async with httpx.AsyncClient() as client:
        try:
            # Tworzymy folder na Yandex Disk
            response = await client.put(
                "https://cloud-api.yandex.net/v1/disk/resources",
                params={"path": folder_path},
                headers={"Authorization": f"OAuth {yandex_token}"},
                timeout=30.0
            )
            
            # Sprawdzamy czy folder został utworzony lub już istnieje
            assert response.status_code in [201, 202, 409], (
                f"Nie udało się utworzyć folderu '{folder_name}' na Yandex Disk. "
                f"Status: {response.status_code}, Response: {response.text}"
            )
            
            # Weryfikujemy że folder istnieje - sprawdzamy informacje o folderze
            check_response = await client.get(
                "https://cloud-api.yandex.net/v1/disk/resources",
                params={"path": folder_path},
                headers={"Authorization": f"OAuth {yandex_token}"},
                timeout=30.0
            )
            
            assert check_response.status_code == 200, (
                f"Folder '{folder_name}' nie istnieje na Yandex Disk. "
                f"Status: {check_response.status_code}"
            )
            
            folder_info = check_response.json()
            assert folder_info.get("type") == "dir", f"'{folder_name}' nie jest katalogiem"
            assert folder_info.get("name") == folder_name, f"Nazwa folderu nie jest '{folder_name}'"
            
        except httpx.HTTPError as e:
            pytest.fail(f"Błąd HTTP podczas komunikacji z Yandex Disk API: {e}")
        except Exception as e:
            pytest.fail(f"Nieoczekiwany błąd podczas tworzenia folderu na Yandex Disk: {e}")
