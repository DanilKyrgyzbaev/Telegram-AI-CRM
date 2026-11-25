from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import get_settings
from app.models import Product


def catalog_url() -> str | None:
    """Адрес каталога-Mini App на нашем сайте; без домена Telegram его не откроет."""
    domain = get_settings().domain
    return f"https://{domain}/app" if domain else None


def catalog_rows() -> list[list[InlineKeyboardButton]]:
    url = catalog_url()
    return [[InlineKeyboardButton(text="🛍 Открыть каталог", web_app=WebAppInfo(url=url))]] if url else []


def subscribe_rows() -> list[list[InlineKeyboardButton]]:
    settings = get_settings()
    if not settings.channel_url:
        return []
    rows = [[InlineKeyboardButton(text="📢 Подписаться на канал", url=settings.channel_url)]]
    if settings.channel_id:
        rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
    return rows


def subscribe_keyboard() -> InlineKeyboardMarkup | None:
    rows = catalog_rows() + subscribe_rows()
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def products_keyboard(products: Sequence[Product], with_subscribe: bool = False) -> InlineKeyboardMarkup | None:
    """Кнопки на карточки Wildberries для товаров, которые порекомендовал AI."""
    rows = [[InlineKeyboardButton(text=f"🛒 {p.name}", url=p.wb_url)] for p in products if p.wb_url]
    if with_subscribe:
        rows += subscribe_rows()
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
