from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import get_settings
from app.models import Product


def subscribe_rows() -> list[list[InlineKeyboardButton]]:
    settings = get_settings()
    if not settings.channel_url:
        return []
    rows = [[InlineKeyboardButton(text="📢 Подписаться на канал", url=settings.channel_url)]]
    if settings.channel_id:
        rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
    return rows


def subscribe_keyboard() -> InlineKeyboardMarkup | None:
    rows = subscribe_rows()
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def products_keyboard(products: Sequence[Product], with_subscribe: bool = False) -> InlineKeyboardMarkup | None:
    """Кнопки на карточки Wildberries для товаров, которые порекомендовал AI."""
    rows = [[InlineKeyboardButton(text=f"🛒 {p.name}", url=p.wb_url)] for p in products if p.wb_url]
    if with_subscribe:
        rows += subscribe_rows()
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
