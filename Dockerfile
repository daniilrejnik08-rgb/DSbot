# Orbis-DSbot — Discord bot (Python 3.11)
# Для хостингов с «своим Dockerfile» (bothost, timeweb, amvera, railway и т.п.)

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data

# Системные пакеты: голос (opus), музыка (ffmpeg), шрифты для Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libopus0 \
        libopus-dev \
        fonts-noto-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python (кэш слоя, пока requirements не меняется)
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Код бота
COPY . .

RUN mkdir -p /app/data

# Токен и настройки — только через env хостинга, не в образ
# DISCORD_TOKEN, GUILD_IDS, LITE_MODE, …

CMD ["python", "-u", "main.py"]
