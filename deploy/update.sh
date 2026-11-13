#!/bin/sh
# Обновление на сервере после загрузки нового кода: пересборка и перезапуск.
# Миграции базы api применяет сам при старте.
set -e
cd "$(dirname "$0")/.."
sh deploy/backup.sh
if grep -q '^DOMAIN=.' .env; then
  docker compose --profile https up -d --build
else
  docker compose up -d --build
fi
docker compose ps
