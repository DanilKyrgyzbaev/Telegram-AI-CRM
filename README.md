# Telegram AI CRM

Telegram-бот с AI-менеджером продаж, CRM и веб-админкой для магазина на Wildberries.

**Стек:** Python 3.12, FastAPI, aiogram 3, SQLAlchemy 2 (async), PostgreSQL, Alembic, SQLAdmin, Claude API.

## Возможности

- **QR на упаковке** → бот: благодарность за покупку, рекомендации с кнопками на карточки WB, промокод WB
- **AI-менеджер** консультирует по каталогу и помнит покупки клиента
- **Рассылки** — сразу или по расписанию, из бота (`/broadcast`, `/scheduled`), админки или API
- **Проверка подписки** на канал и учёт подписок
- **Учёт рекламы** — ссылки `t.me/<bot>?start=<метка>`
- **Админка** `/admin` — клиенты, диалоги, покупки, товары, промокоды, кампании, рассылки

## Структура

```
app/
  config.py            настройки из .env
  db.py                подключение к PostgreSQL
  models.py            таблицы базы
  admin.py             веб-админка (SQLAdmin)
  ai/manager.py        AI-менеджер (Claude API)
  services/            бизнес-логика: рассылки, планировщик, QR, промокоды, подписка
  bot/                 Telegram-бот (aiogram)
    handlers/          /start и QR, диалог с AI, рассылки, подписка на канал
    keyboards.py       кнопки: товары WB, подписка
  api/                 CRM API (FastAPI): /api/...
migrations/            миграции базы (Alembic)
deploy/                Caddy (HTTPS), бэкап, обновление на сервере
```

## Сервер

Пошаговая инструкция: [DEPLOY.md](DEPLOY.md).

## Локальная разработка (macOS)

```bash
brew install python@3.12 postgresql@16 && brew services start postgresql@16
psql -d postgres -c "CREATE USER crm WITH PASSWORD 'crm'" -c "CREATE DATABASE crm OWNER crm"
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env               # DATABASE_URL=...@localhost:5432/crm, заполнить ключи
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.api.main:app --reload   # API и админка: http://localhost:8000/admin
.venv/bin/python -m app.bot.main              # бот
```

После добавления зависимостей обновите зафиксированные версии для сервера:
`.venv/bin/pip freeze | grep -viE "^(pip|setuptools|wheel)==" > requirements.lock`

- Админка: http://localhost:8000/admin (`ADMIN_USERNAME` / `ADMIN_PASSWORD` из `.env`)
- API и документация: http://localhost:8000/docs (заголовок `X-API-Key`)
