FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app
COPY indexer /app/indexer

ENV PYTHONPATH=/app

CMD ["gunicorn", "backend.wsgi:application", "--bind", "0.0.0.0:8000"]
