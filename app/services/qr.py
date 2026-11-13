import io
import re

import segno
from aiogram import Bot

from app.config import get_settings

_bot_username: str | None = None


def start_param(product_id: int) -> str:
    """Параметр deep-link для QR на упаковке: t.me/<bot>?start=p15"""
    return f"p{product_id}"


def parse_start_param(args: str | None) -> int | None:
    """ID товара из параметра /start или None, если это не QR товара."""
    match = re.fullmatch(r"p(\d+)", args or "")
    return int(match.group(1)) if match else None


async def bot_username() -> str:
    global _bot_username
    if _bot_username is None:
        bot = Bot(get_settings().bot_token)
        try:
            _bot_username = (await bot.get_me()).username
        finally:
            await bot.session.close()
    return _bot_username


async def product_link(product_id: int) -> str:
    return f"https://t.me/{await bot_username()}?start={start_param(product_id)}"


def qr_png(link: str) -> bytes:
    buffer = io.BytesIO()
    # Уровень коррекции M — QR читается, даже если упаковка немного помята
    segno.make(link, error="m").save(buffer, kind="png", scale=12, border=2)
    return buffer.getvalue()
