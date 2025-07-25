# 1. Базовый образ с Python
FROM python:3.11-slim

# 2. Установка рабочей директории внутри контейнера
WORKDIR /app

# 3. Копирование файла с зависимостями и их установка
# Этот шаг кэшируется, чтобы не переустанавливать зависимости при каждом изменении кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Устанавливаем браузеры для Playwright
RUN playwright install --with-deps

# 4. Копирование всего остального кода приложения
COPY . .

# Команда для запуска API по умолчанию (может быть переопределена в docker-compose)
CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"] 