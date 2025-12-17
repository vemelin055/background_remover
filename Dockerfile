FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов приложения
COPY . .

# Создание директории для шаблонов
RUN mkdir -p templates && \
    chmod 755 templates

# Открытие порта (Railway использует переменную PORT)
EXPOSE 8000

# Команда запуска (Railway автоматически устанавливает PORT через переменную окружения)
# railway.json имеет startCommand, который использует $PORT
# Если railway.json не используется, main.py уже использует os.getenv("PORT", 8000)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

