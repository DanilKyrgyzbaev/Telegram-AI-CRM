FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# requirements.lock — точные версии, проверенные локально: сборка на сервере не подтянет несовместимое обновление
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY . .
