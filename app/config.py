from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значения из .env.example: с ними запускаться нельзя — они известны всем, кто видел репозиторий
INSECURE_SECRETS = {"", "change-me"}
MIN_SECRET_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    channel_url: str = ""
    # @username или числовой ID канала (-100...). Бот должен быть админом канала
    channel_id: str = ""
    # True — AI-менеджер отвечает только подписчикам канала
    require_subscription: bool = False
    # True — посты, которые AI написал сам (новый товар, промокод), публикуются в канал без подтверждения
    channel_autopublish: bool = False
    # Название бренда для постов в канал и ссылка на все его товары на WB (кнопка под постом)
    shop_name: str = ""
    shop_url: str = ""
    # Владелец магазина и почта для обращений — на странице политики конфиденциальности
    shop_legal_name: str = ""
    contact_email: str = ""
    # Instagram магазина — кнопка под постами в канале
    instagram_url: str = ""
    # Домен сервера (тот же, что для HTTPS админки). Нужен Instagram: он сам скачивает фото для постов
    domain: str = ""
    # Instagram API (вход через Instagram). Пусто — интеграция выключена
    instagram_account_id: str = ""
    instagram_access_token: str = ""
    # App Secret приложения Meta — им проверяем, что webhook прислал именно Meta
    instagram_app_secret: str = ""
    # Любая строка; та же вписывается в настройках webhook в кабинете Meta
    instagram_verify_token: str = ""
    instagram_api_version: str = "v23.0"
    # graph.instagram.com — токен входа через Instagram (60 дней, продлевается сам);
    # graph.facebook.com — бессрочный токен системного пользователя (единый вход, новые приложения Meta)
    instagram_graph_host: str = "graph.instagram.com"
    database_url: str = "postgresql+asyncpg://crm:crm@localhost:5432/crm"
    ai_model: str = "claude-opus-5-5"
    admin_api_key: str = ""
    # Вход в веб-админку /admin. Пустой пароль — вход запрещён
    admin_username: str = "admin"
    admin_password: str = ""
    # Ключ для подписи cookie сессии админки
    secret_key: str = ""
    # Telegram ID админов, которым доступны команды бота вроде /broadcast
    admin_ids: list[int] = []
    # Часовой пояс, в котором админ вводит время отложенных рассылок в боте
    timezone: str = "UTC"
    # Сколько сообщений клиента AI-менеджер обрабатывает за минуту и за сутки. 0 — без лимита
    ai_messages_per_minute: int = 5
    ai_messages_per_day: int = 50
    # Повторный скан QR того же товара в течение стольких дней не считается новой покупкой
    qr_repeat_days: int = 30
    # Сколько разных QR один клиент может отсканировать за сутки. 0 — без лимита
    qr_scans_per_day: int = 5

    @property
    def instagram_enabled(self) -> bool:
        return bool(self.instagram_account_id and self.instagram_access_token)

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        for name in ("secret_key", "admin_api_key"):
            value = getattr(self, name)
            if value in INSECURE_SECRETS or len(value) < MIN_SECRET_LENGTH:
                raise ValueError(
                    f"{name.upper()} в .env не задан или слишком простой. "
                    f"Сгенерируйте свой (не короче {MIN_SECRET_LENGTH} символов): openssl rand -hex 32"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
