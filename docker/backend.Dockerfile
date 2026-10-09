# API · 워커 · 유지보수 작업이 같은 이미지를 쓴다 (명령만 다름)
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker ./worker
COPY apps/api ./apps/api
COPY scripts ./scripts

ENV PYTHONPATH=/app:/app/apps/api \
    PYTHONUNBUFFERED=1
RUN useradd --create-home app
USER app
