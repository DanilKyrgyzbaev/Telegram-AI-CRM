#!/bin/sh
# Резервная копия базы. Хранит последние 14 копий в папке backups/.
# Запуск по расписанию (каждую ночь в 3:00): crontab -e →
#   0 3 * * * cd /opt/telegram-ai-crm && sh deploy/backup.sh >> backups/backup.log 2>&1
set -e
cd "$(dirname "$0")/.."
mkdir -p backups
. ./.env
FILE="backups/crm-$(date +%Y-%m-%d_%H-%M).sql.gz"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$FILE"
ls -1t backups/crm-*.sql.gz | tail -n +15 | xargs -r rm --
echo "$(date) backup saved: $FILE"
