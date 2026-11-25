import io
import re

import segno
from aiogram import Bot

from app.config import get_settings

_bot_username: str | None = None


_QR_PARAM = re.compile(r"q([0-9a-f]{12})")
# Старый формат ссылок (p<номер товара>) легко подобрать перебором — он больше не засчитывается
_LEGACY_QR_PARAM = re.compile(r"p\d+")
# Ссылки из Telegram Mini App (каталога): «app» — общий вопрос, «ask<ID товара>» — вопрос о товаре
APP_START_PARAM = "app"
ASK_START_PREFIX = "ask"
_ASK_PARAM = re.compile(ASK_START_PREFIX + r"(\d+)")


def start_param(qr_token: str) -> str:
    """Параметр deep-link для QR на упаковке: t.me/<bot>?start=q3f9a1c07b2de"""
    return f"q{qr_token}"


def parse_start_param(args: str | None) -> str | None:
    """Код товара (Product.qr_token) из параметра /start или None, если это не QR товара."""
    match = _QR_PARAM.fullmatch(args or "")
    return match.group(1) if match else None


def parse_ask_param(args: str | None) -> int | None:
    """ID товара, о котором клиент хочет спросить из каталога, или None."""
    match = _ASK_PARAM.fullmatch(args or "")
    return int(match.group(1)) if match else None


def is_app_param(args: str | None) -> bool:
    return args == APP_START_PARAM or parse_ask_param(args) is not None


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
