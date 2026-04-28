FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для voice/music:
# - ffmpeg: проигрывание/обработка аудио
# - libopus0: библиотека Opus для discord voice
# - fonts-noto-core: кириллица в Pillow-рендерах
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libopus0 fonts-noto-core && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/app/data
RUN mkdir -p /app/data

CMD ["python", "main.py"]
