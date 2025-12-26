#!/usr/bin/env python3
"""
Test sprawdzający czy kod Replicate działa z lokalnym plikiem
"""
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Dodajemy katalog główny do ścieżki, żeby importować main
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

# Importujemy funkcję process_replicate z main.py
from main import process_replicate

async def test_replicate_with_local_file():
    """Test procesowania lokalnego pliku przez Replicate"""
    
    # Ścieżka do pliku testowego (z terminala)
    test_file_path = os.path.expanduser("~/Downloads/1 (1).jpg")
    
    if not os.path.exists(test_file_path):
        print(f"❌ Plik testowy nie istnieje: {test_file_path}")
        print("   Sprawdź czy plik '1 (1).jpg' istnieje w katalogu Downloads")
        return False
    
    print(f"✅ Znaleziono plik testowy: {test_file_path}")
    print(f"   Rozmiar: {os.path.getsize(test_file_path)} bajtów")
    
    # Sprawdzamy czy API key jest ustawiony
    api_key = os.getenv("REPLICATE_API_KEY")
    if not api_key:
        print("❌ REPLICATE_API_KEY nie jest ustawiony w zmiennych środowiskowych")
        print("   Ustaw REPLICATE_API_KEY w .env lub Railway variables")
        return False
    
    print(f"✅ REPLICATE_API_KEY jest ustawiony (długość: {len(api_key)} znaków)")
    
    # Wczytujemy plik
    try:
        with open(test_file_path, 'rb') as f:
            image_bytes = f.read()
        print(f"✅ Wczytano plik: {len(image_bytes)} bajtów")
    except Exception as e:
        print(f"❌ Błąd podczas wczytywania pliku: {str(e)}")
        return False
    
    # Testujemy funkcję process_replicate
    try:
        print("\n🔄 Przetwarzanie obrazu przez Replicate...")
        print("   (to może zająć kilka sekund...)")
        
        # Używamy logging do wyświetlania postępu
        import logging
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        
        result_bytes = await process_replicate(image_bytes, api_key)
        
        print(f"\n✅ Przetwarzanie zakończone pomyślnie!")
        print(f"   Rozmiar wyniku: {len(result_bytes)} bajtów")
        
        # Zapisujemy wynik do pliku testowego
        output_path = "test_output.png"
        with open(output_path, 'wb') as f:
            f.write(result_bytes)
        print(f"✅ Wynik zapisano do: {output_path}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Błąd podczas przetwarzania: {str(e)}")
        import traceback
        print("\nSzczegółowy traceback:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Test Replicate API z lokalnym plikiem")
    print("=" * 60)
    print()
    
    success = asyncio.run(test_replicate_with_local_file())
    
    print()
    print("=" * 60)
    if success:
        print("✅ TEST ZAKOŃCZONY POMYŚLNIE")
        sys.exit(0)
    else:
        print("❌ TEST NIE POWIODŁ SIĘ")
        sys.exit(1)

