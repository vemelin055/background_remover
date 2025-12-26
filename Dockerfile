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

# Создание директории для шаблонов и фонов
RUN mkdir -p templates && \
    mkdir -p background && \
    chmod 755 templates && \
    chmod 755 background

# Открытие порта (Railway использует переменную PORT)
EXPOSE 8000

# Команда запуска
# Railway автоматически устанавливает PORT через переменную окружения
# main.py уже использует os.getenv("PORT", 8000), поэтому możemy просто uruchomić main.py
# Railway.json имеет startCommand, который будет использоваться вместо CMD
CMD ["python", "main.py"]

