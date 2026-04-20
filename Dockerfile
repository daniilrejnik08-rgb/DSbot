FROM python:3.11-slim

WORKDIR /app

# ffmpeg + libopus для музыки в голосе. Если хостинг без apt — см. Dockerfile.alpine
# или переменная окружения OPUS_LIBRARY_PATH=/полный/путь/libopus.so.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
