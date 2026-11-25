from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config import get_settings
from app.models import Product


# Подбор размера: ответы-кнопки под полем ввода. Нажатие отправляет сообщение от имени клиента.
# Подписи уникальны (см / кг), по ним бот понимает, на какой шаг ответили
HEIGHTS = ("до 160 см", "160–165 см", "166–170 см", "171–175 см", "176–180 см", "181–185 см", "выше 185 см")
WEIGHTS = ("до 50 кг", "50–55 кг", "56–60 кг", "61–65 кг", "66–70 кг", "71–80 кг", "81–90 кг", "больше 90 кг")
FITS = ("По фигуре", "Свободно", "Оверсайз")


def _reply_keyboard(options: tuple[str, ...], per_row: int, placeholder: str) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=o) for o in options[i:i + per_row]] for i in range(0, len(options), per_row)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder=placeholder)


def height_keyboard() -> ReplyKeyboardMarkup:
    return _reply_keyboard(HEIGHTS, 3, "Или напишите рост")


def weight_keyboard() -> ReplyKeyboardMarkup:
    return _reply_keyboard(WEIGHTS, 4, "Или напишите вес")


def fit_keyboard() -> ReplyKeyboardMarkup:
    return _reply_keyboard(FITS, 3, "Или опишите, как любите носить")


def catalog_url() -> str | None:
    """Адрес каталога-Mini App на нашем сайте; без домена Telegram его не откроет."""
    domain = get_settings().domain
    return f"https://{domain}/app" if domain else None


def catalog_menu_button() -> MenuButtonWebApp | None:
    """Кнопка «Каталог» слева от поля ввода в чате с ботом."""
    url = catalog_url()
    return MenuButtonWebApp(text="Каталог", web_app=WebAppInfo(url=url)) if url else None


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
