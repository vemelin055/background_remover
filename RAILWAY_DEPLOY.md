# Railway Deployment Guide

## Wymagane zmienne środowiskowe

Wszystkie wrażliwe dane muszą być ustawione jako zmienne środowiskowe w Railway. Oto pełna lista:

### API Keys (opcjonalne - można ustawić w panelu API keys w aplikacji)
- `REMOVEBG_API_KEY` - API key dla Remove.bg
- `CLIPDROP_API_KEY` - API key dla Clipdrop
- `REPLICATE_API_KEY` - API key dla Replicate
- `FAL_KEY` - API key dla FAL (fal.ai)

### Yandex Disk OAuth (wymagane dla funkcji Yandex Disk)
- `YANDEX_DISK_CLIENT_ID` - Client ID z aplikacji OAuth Yandex
- `YANDEX_DISK_CLIENT_SECRET` - Client Secret z aplikacji OAuth Yandex
- `YANDEX_DISK_REDIRECT_URI` - Redirect URI (np. `https://your-app.railway.app/auth/yandex/callback`)
- `YANDEX_DISK_TOKEN` - Access token OAuth (opcjonalne, można uzyskać przez autoryzację w aplikacji)

### Railway automatycznie ustawia:
- `PORT` - Port na którym działa aplikacja (automatycznie ustawiane przez Railway)

## Instrukcja deploymentu

### 1. Przygotowanie na Railway

1. Zaloguj się do [Railway](https://railway.app/)
2. Utwórz nowy projekt
3. Połącz z repozytorium GitHub lub użyj Railway CLI

### 2. Ustawienie zmiennych środowiskowych

W Railway Dashboard:
1. Przejdź do swojego projektu
2. Kliknij na "Variables"
3. Dodaj wszystkie wymagane zmienne:

```bash
# API Keys (opcjonalne)
REMOVEBG_API_KEY=your_removebg_key
CLIPDROP_API_KEY=your_clipdrop_key
REPLICATE_API_KEY=your_replicate_key
FAL_KEY=your_fal_key

# Yandex Disk OAuth (wymagane)
YANDEX_DISK_CLIENT_ID=your_client_id
YANDEX_DISK_CLIENT_SECRET=your_client_secret
YANDEX_DISK_REDIRECT_URI=https://your-app.railway.app/auth/yandex/callback
YANDEX_DISK_TOKEN=your_access_token  # opcjonalne
```

### 3. Konfiguracja Yandex Disk OAuth

1. Przejdź do https://oauth.yandex.ru/
2. Utwórz nową aplikację
3. Ustaw Redirect URI na: `https://your-app.railway.app/auth/yandex/callback`
4. Skopiuj Client ID i Client Secret do Railway variables

### 4. Deployment

Railway automatycznie:
- Wykryje Dockerfile
- Zbuduje obraz
- Uruchomi aplikację na porcie z zmiennej `PORT`

### 5. Weryfikacja

Po deployment:
1. Sprawdź czy aplikacja działa: `https://your-app.railway.app`
2. Sprawdź logi w Railway Dashboard
3. Przetestuj funkcjonalność

## Ważne uwagi

- **Wszystkie wrażliwe dane są w zmiennych środowiskowych** - nie ma hardcoded wartości
- **PORT jest automatycznie ustawiany przez Railway** - kod używa `os.getenv("PORT", 8000)`
- **Redirect URI musi być ustawiony w Railway variables** - nie używa hardcoded localhost
- **API keys można ustawić w Railway variables lub w panelu aplikacji** - aplikacja sprawdza najpierw localStorage, potem .env

## Troubleshooting

### Aplikacja nie startuje
- Sprawdź logi w Railway Dashboard
- Upewnij się, że wszystkie wymagane zmienne są ustawione
- Sprawdź czy PORT jest ustawiony (Railway robi to automatycznie)

### Yandex Disk nie działa
- Sprawdź czy `YANDEX_DISK_CLIENT_ID` i `YANDEX_DISK_CLIENT_SECRET` są ustawione
- Sprawdź czy `YANDEX_DISK_REDIRECT_URI` wskazuje na prawidłowy URL Railway
- Upewnij się, że redirect URI w Yandex OAuth aplikacji pasuje do Railway URL

### API keys nie działają
- Sprawdź czy klucze są poprawne
- Sprawdź czy są ustawione w Railway variables lub w panelu aplikacji
- Sprawdź logi dla błędów API




