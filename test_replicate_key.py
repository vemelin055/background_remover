"""
Test sprawdzający czy REPLICATE_API_KEY jest dostępny w zmiennych środowiskowych
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def test_replicate_api_key():
    """Test sprawdzający obecność REPLICATE_API_KEY"""
    api_key = os.getenv("REPLICATE_API_KEY")
    
    if api_key:
        print("✅ REPLICATE_API_KEY jest ustawiony w zmiennych środowiskowych")
        print(f"   Długość klucza: {len(api_key)} znaków")
        print(f"   Prefix klucza: {api_key[:4]}...")
        return True
    else:
        print("❌ REPLICATE_API_KEY NIE jest ustawiony w zmiennych środowiskowych")
        print("   Sprawdź:")
        print("   1. Czy plik .env zawiera REPLICATE_API_KEY=...")
        print("   2. Czy w Railway variables jest ustawiony REPLICATE_API_KEY")
        return False

if __name__ == "__main__":
    success = test_replicate_api_key()
    sys.exit(0 if success else 1)


