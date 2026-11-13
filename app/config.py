from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    channel_url: str = ""
    # @username или числовой ID канала (-100...). Бот должен быть админом канала
    channel_id: str = ""
    # True — AI-менеджер отвечает только подписчикам канала
    require_subscription: bool = False
    database_url: str = "postgresql+asyncpg://crm:crm@localhost:5432/crm"
    ai_model: str = "claude-opus-5-5"
    admin_api_key: str = "change-me"
    # Вход в веб-админку /admin. Пустой пароль — вход запрещён
    admin_username: str = "admin"
    admin_password: str = ""
    # Ключ для подписи cookie сессии админки
    secret_key: str = "change-me"
    # Telegram ID админов, которым доступны команды бота вроде /broadcast
    admin_ids: list[int] = []
    # Часовой пояс, в котором админ вводит время отложенных рассылок в боте
    timezone: str = "UTC"


@lru_cache
def get_settings() -> Settings:
    return Settings()
