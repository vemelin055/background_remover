"""
Skrypt do uzyskania nowego access tokena OAuth dla Yandex Disk

INSTRUKCJA:
1. Uruchom aplikację: python main.py
2. Otwórz w przeglądarce: http://localhost:8000
3. Kliknij "Авторизоваться" w sekcji Яндекс Диск
4. Zaloguj się na NOWE konto Yandex (to, które chcesz użyć)
5. Po autoryzacji, token zostanie wyświetlony w oknie lub zapisany w localStorage przeglądarki

ALTERNATYWNIE - ręczne uzyskanie tokena przez OAuth flow:
1. Otwórz w przeglądarce URL autoryzacji (patrz poniżej)
2. Zaloguj się na nowe konto Yandex
3. Skopiuj kod autoryzacyjny z URL callback
4. Użyj tego kodu do uzyskania access tokena (patrz funkcja get_token_from_code)
"""

import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()


def print_auth_url():
    """Wyświetla URL do autoryzacji OAuth"""
    client_id = os.getenv("YANDEX_DISK_CLIENT_ID")
    redirect_uri = os.getenv("YANDEX_DISK_REDIRECT_URI", "http://localhost:8000/auth/yandex/callback")
    
    if not client_id:
        print("❌ BŁĄD: YANDEX_DISK_CLIENT_ID nie jest ustawiony w .env")
        return
    
    auth_url = f"https://oauth.yandex.ru/authorize?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
    
    print("\n" + "="*70)
    print("AUTORYZACJA YANDEX DISK - NOWE KONTO")
    print("="*70)
    print(f"\n1. Otwórz ten URL w przeglądarce:")
    print(f"   {auth_url}\n")
    print("2. Zaloguj się na NOWE konto Yandex (to, które chcesz użyć)")
    print("3. Po autoryzacji, zostaniesz przekierowany do callback URL")
    print("4. Z URL callback skopiuj parametr 'code' (kod autoryzacyjny)")
    print("5. Uruchom: python get_yandex_token.py --code YOUR_CODE_HERE")
    print("\n" + "="*70 + "\n")


async def get_token_from_code(auth_code: str):
    """Uzyskuje access token z kodu autoryzacyjnego"""
    client_id = os.getenv("YANDEX_DISK_CLIENT_ID")
    client_secret = os.getenv("YANDEX_DISK_CLIENT_SECRET")
    redirect_uri = os.getenv("YANDEX_DISK_REDIRECT_URI", "http://localhost:8000/auth/yandex/callback")
    
    if not client_id or not client_secret:
        print("❌ BŁĄD: YANDEX_DISK_CLIENT_ID lub YANDEX_DISK_CLIENT_SECRET nie są ustawione w .env")
        return None
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://oauth.yandex.ru/token",
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "client_id": client_id,
                    "client_secret": client_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token")
                
                print("\n" + "="*70)
                print("✅ SUKCES! Access token uzyskany")
                print("="*70)
                print(f"\nAccess Token: {access_token}\n")
                print("Aby użyć tego tokena, dodaj do pliku .env:")
                print(f"YANDEX_DISK_TOKEN={access_token}\n")
                print("="*70 + "\n")
                
                return access_token
            else:
                print(f"❌ BŁĄD: Nie udało się uzyskać tokena. Status: {response.status_code}")
                print(f"Odpowiedź: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Błąd: {e}")
            return None


async def verify_token(token: str):
    """Weryfikuje token i pokazuje informacje o koncie"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://cloud-api.yandex.net/v1/disk",
                headers={"Authorization": f"OAuth {token}"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                user_info = data.get("user", {})
                
                print("\n" + "="*70)
                print("INFORMACJE O KONCIE (weryfikacja tokena)")
                print("="*70)
                print(f"Login (Email): {user_info.get('login', 'Nieznany')}")
                print(f"Nazwa wyświetlana: {user_info.get('display_name', 'Nieznany')}")
                print(f"UID: {user_info.get('uid', 'Nieznany')}")
                print("="*70 + "\n")
                
                return True
            else:
                print(f"❌ Token jest nieprawidłowy. Status: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Błąd podczas weryfikacji tokena: {e}")
            return False


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--code" and len(sys.argv) > 2:
        # Uzyskaj token z kodu autoryzacyjnego
        code = sys.argv[2]
        token = asyncio.run(get_token_from_code(code))
        if token:
            asyncio.run(verify_token(token))
    elif len(sys.argv) > 1 and sys.argv[1] == "--verify" and len(sys.argv) > 2:
        # Weryfikuj istniejący token
        token = sys.argv[2]
        asyncio.run(verify_token(token))
    else:
        # Pokaż instrukcje
        print_auth_url()



