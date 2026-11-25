import io
import re

import segno
from aiogram import Bot

from app.config import get_settings

_bot_username: str | None = None


_QR_PARAM = re.compile(r"q([0-9a-f]{12})")
# Старый формат ссылок (p<номер товара>) легко подобрать перебором — он больше не засчитывается
_LEGACY_QR_PARAM = re.compile(r"p\d+")
# Вопрос о конкретном товаре: «ask<ID>» — из каталога в Telegram (Mini App), «size<ID>» — кнопка
# «Спросить про размер» на сайте. «app» — общий вопрос из каталога
APP_START_PARAM = "app"
ASK_START_PREFIX = "ask"
SIZE_START_PREFIX = "size"
_PRODUCT_QUESTION = re.compile(rf"({ASK_START_PREFIX}|{SIZE_START_PREFIX})(\d+)")


def start_param(qr_token: str) -> str:
    """Параметр deep-link для QR на упаковке: t.me/<bot>?start=q3f9a1c07b2de"""
    return f"q{qr_token}"


def parse_start_param(args: str | None) -> str | None:
    """Код товара (Product.qr_token) из параметра /start или None, если это не QR товара."""
    match = _QR_PARAM.fullmatch(args or "")
    return match.group(1) if match else None


def parse_product_question(args: str | None) -> tuple[str, int] | None:
    """(«ask» или «size», ID товара), если клиент пришёл спросить о товаре, иначе None."""
    match = _PRODUCT_QUESTION.fullmatch(args or "")
    return (match.group(1), int(match.group(2))) if match else None


def source_for(args: str | None) -> str | None:
    """Источник клиента для CRM по параметру /start: QR, каталог в Telegram, сайт или метка рекламы."""
    if is_qr_param(args):
        return "qr"
    if args == APP_START_PARAM or args and args.startswith(ASK_START_PREFIX) and parse_product_question(args):
        return "app"
    if parse_product_question(args):
        return "site"
    return args


def is_qr_param(args: str | None) -> bool:
    """Параметр /start похож на QR с упаковки (в том числе старого формата), а не на метку рекламы."""
    return bool(_QR_PARAM.fullmatch(args or "") or _LEGACY_QR_PARAM.fullmatch(args or ""))


async def bot_username() -> str:
    global _bot_username
    if _bot_username is None:
        bot = Bot(get_settings().bot_token)
        try:
            _bot_username = (await bot.get_me()).username
        finally:
            await bot.session.close()
    return _bot_username


async def product_link(qr_token: str) -> str:
    return f"https://t.me/{await bot_username()}?start={start_param(qr_token)}"


def qr_png(link: str) -> bytes:
    buffer = io.BytesIO()
    # Уровень коррекции M — QR читается, даже если упаковка немного помята
    segno.make(link, error="m").save(buffer, kind="png", scale=12, border=2)
    return buffer.getvalue()
