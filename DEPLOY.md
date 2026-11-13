# Развёртывание на сервере

Бот, AI-менеджер, админка и база работают круглосуточно на VPS в Docker.
После сбоя или перезагрузки сервера всё поднимается само.

## 1. Сервер

- **ОС:** Ubuntu 24.04
- **Ресурсы:** 1 vCPU, 2 ГБ RAM, 20 ГБ диска — хватит с запасом (~$5–10/мес)
- **Страна — НЕ Россия.** Claude API не работает с российских IP, AI-менеджер будет молчать.
  Подойдут Нидерланды, Германия, Финляндия и т. п. (Hetzner, DigitalOcean, Vultr, Aeza и др.)

После покупки провайдер пришлёт IP-адрес и пароль `root`.

## 2. Установка Docker

С вашего Mac:

```bash
ssh root@IP_СЕРВЕРА
```

На сервере:

```bash
curl -fsSL https://get.docker.com | sh
# Файрвол: открыть только SSH и HTTPS
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 3. Загрузка проекта

С вашего Mac (из папки проекта):

```bash
rsync -av --exclude '.venv*' --exclude '.idea' --exclude '__pycache__' --exclude '.env' \
  "./" root@IP_СЕРВЕРА:/opt/telegram-ai-crm/
```

## 4. Настройки `.env` на сервере

```bash
cd /opt/telegram-ai-crm
cp .env.example .env
nano .env
```

Заполните (значения для сервера — **новые**, не копируйте локальные пароли):

| Параметр | Что вписать |
|---|---|
| `BOT_TOKEN` | Токен бота (после `/revoke` в @BotFather — новый) |
| `ANTHROPIC_API_KEY` | Ключ Claude API (лучше создать отдельный для сервера) |
| `ADMIN_IDS` | `[761517835]` |
| `CHANNEL_URL`, `CHANNEL_ID` | `https://t.me/Miss_Way`, `@Miss_Way` |
| `TIMEZONE` | Ваш часовой пояс, например `Europe/Moscow` |
| `POSTGRES_PASSWORD` | Длинный случайный пароль: `openssl rand -hex 16` |
| `ADMIN_PASSWORD` | Пароль входа в админку: `openssl rand -base64 12` |
| `ADMIN_API_KEY`, `SECRET_KEY` | `openssl rand -hex 32` (каждому свой) |
| `DOMAIN` | Домен админки (см. п. 6) или пусто |

`DATABASE_URL` менять не нужно — в Docker адрес базы подставляется автоматически.

## 5. Запуск

> ⚠️ Сначала остановите бота на Mac — Telegram не даёт одному боту работать в двух местах.

```bash
docker compose up -d --build        # без домена
# или с доменом и HTTPS:
docker compose --profile https up -d --build
```

Проверка:

```bash
docker compose ps                   # все сервисы должны быть running / healthy
docker compose logs -f bot          # должно быть «Run polling for bot @Miss_Way_bot»
```

Напишите боту в Telegram — он должен ответить.

## 6. Вход в админку

**Вариант А — с доменом (удобно, можно с телефона).**
Купите домен (или используйте поддомен своего), в DNS добавьте запись `A`: `crm.ваш-домен.ru → IP_СЕРВЕРА`.
Впишите `DOMAIN=crm.ваш-домен.ru` в `.env` и запустите с `--profile https`.
Админка: `https://crm.ваш-домен.ru/admin` — сертификат HTTPS Caddy получит сам.

**Вариант Б — без домена (через SSH-туннель).**
Админка снаружи закрыта. На Mac:

```bash
ssh -L 8000:localhost:8000 root@IP_СЕРВЕРА
```

Пока окно открыто, админка доступна на Mac: http://localhost:8000/admin

## 7. Резервные копии базы

Ежедневный бэкап в 3:00, хранятся последние 14:

```bash
crontab -e
# добавить строку:
0 3 * * * cd /opt/telegram-ai-crm && sh deploy/backup.sh >> backups/backup.log 2>&1
```

Ручной бэкап: `sh deploy/backup.sh`. Восстановление:

```bash
gunzip -c backups/crm-ДАТА.sql.gz | docker compose exec -T db psql -U crm crm
```

Время от времени скачивайте бэкапы на Mac: `scp root@IP_СЕРВЕРА:/opt/telegram-ai-crm/backups/*.gz ./`

## 8. Обновление кода

С Mac загрузите новый код (команда из п. 3), затем на сервере:

```bash
cd /opt/telegram-ai-crm && sh deploy/update.sh
```

Скрипт делает бэкап, пересобирает и перезапускает сервисы; миграции базы применяются автоматически.

## 9. Перенос данных с Mac (по желанию)

Если в локальной базе уже есть товары и клиенты:

```bash
# на Mac
/opt/homebrew/opt/postgresql@16/bin/pg_dump -U crm --data-only --exclude-table=alembic_version crm > crm-data.sql
scp crm-data.sql root@IP_СЕРВЕРА:/opt/telegram-ai-crm/
# на сервере (после первого запуска, когда таблицы созданы)
docker compose exec -T db psql -U crm crm < crm-data.sql
```

## Полезные команды

```bash
docker compose logs -f bot          # журнал бота
docker compose logs -f api          # журнал API и админки
docker compose restart bot          # перезапуск бота (например, после правки .env)
docker compose down                 # остановить всё (данные базы сохраняются)
```
