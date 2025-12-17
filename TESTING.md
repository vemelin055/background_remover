# Инструкция по тестированию

## Локальное тестирование

### Быстрый старт с Docker Compose

1. Убедитесь, что Docker и Docker Compose установлены

2. Создайте `.env` файл:
```bash
cp .env.example .env
```

3. Заполните необходимые переменные в `.env`:
   - Минимум: один из API ключей (REMOVEBG_API_KEY, CLIPDROP_API_KEY, и т.д.)
   - Для Яндекс Диска: YANDEX_DISK_CLIENT_ID, YANDEX_DISK_CLIENT_SECRET

4. Запустите:
```bash
docker-compose up --build
```

5. Откройте http://localhost:8000

6. Для остановки:
```bash
docker-compose down
```

### Тестирование без Docker (с .venv)

1. Создайте виртуальное окружение:
```bash
python -m venv .venv
```

2. Активируйте виртуальное окружение:
   - macOS/Linux:
   ```bash
   source .venv/bin/activate
   ```
   - Windows:
   ```bash
   .venv\Scripts\activate
   ```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте и заполните `.env` файл

5. Запустите:
```bash
python main.py
```

6. Откройте http://localhost:8000

7. Для деактивации:
```bash
deactivate
```

### Тестирование без Docker (без .venv)

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Создайте и заполните `.env` файл

3. Запустите:
```bash
python main.py
```

4. Откройте http://localhost:8000

## Тестирование на Railway

### Подготовка

1. Создайте аккаунт на [Railway](https://railway.app/)

2. Установите Railway CLI (опционально):
```bash
npm i -g @railway/cli
```

### Деплой через GitHub

1. Создайте репозиторий на GitHub

2. Запушьте код:
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin <your-repo-url>
git push -u origin main
```

3. В Railway Dashboard:
   - New Project → Deploy from GitHub repo
   - Выберите репозиторий
   - Railway автоматически определит Dockerfile

4. Добавьте переменные окружения в Railway:
   - Settings → Variables
   - Добавьте все необходимые переменные из `.env.example`
   - **Важно**: Обновите `YANDEX_DISK_REDIRECT_URI` после получения URL приложения

5. После деплоя:
   - Получите URL приложения (например: `https://your-app.railway.app`)
   - Обновите `YANDEX_DISK_REDIRECT_URI` в настройках Railway
   - Перезапустите сервис

### Деплой через CLI

1. Войдите в Railway:
```bash
railway login
```

2. Инициализируйте проект:
```bash
railway init
```

3. Добавьте переменные окружения:
```bash
railway variables set REMOVEBG_API_KEY=your_key
railway variables set CLIPDROP_API_KEY=your_key
# и т.д.
```

4. Задеплойте:
```bash
railway up
```

## Проверка работоспособности

### Тест API

1. Проверьте главную страницу:
```bash
curl http://localhost:8000/
```

2. Проверьте API endpoint (требует API ключ):
```bash
curl -X POST http://localhost:8000/api/process \
  -F "image=@test.jpg" \
  -F "model=removebg" \
  -F "apiKey=your_api_key"
```

### Тест через браузер

1. Откройте http://localhost:8000 (или ваш Railway URL)

2. Выберите модель API

3. Введите API ключ и нажмите "Сохранить"

4. Загрузите тестовое изображение

5. Нажмите "Обработать"

6. Проверьте результат

## Устранение проблем

### Порт занят

Если порт 8000 занят, измените в `.env`:
```
PORT=8001
```

Или в docker-compose.yml:
```yaml
ports:
  - "8001:8000"
```

### Ошибки с API ключами

- Убедитесь, что API ключи правильно скопированы в `.env`
- Проверьте, что ключи активны и не истекли
- Для FAL используйте `FAL_KEY` из https://fal.ai/

### Проблемы с Яндекс Диском

- Проверьте, что `YANDEX_DISK_REDIRECT_URI` точно совпадает с настройками в OAuth приложении
- Для Railway используйте HTTPS URL
- Убедитесь, что приложение имеет права на Яндекс Диск API

### Docker проблемы

- Убедитесь, что Docker запущен
- Проверьте логи: `docker-compose logs`
- Пересоберите образ: `docker-compose up --build --force-recreate`

## Логи

### Docker Compose
```bash
docker-compose logs -f
```

### Railway
- В Railway Dashboard: View Logs
- Или через CLI: `railway logs`

