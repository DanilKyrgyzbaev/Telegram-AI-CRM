"""Защита от накрутки: лимиты на обращения к AI и на сканирование QR.

Каждый ответ AI стоит денег, а QR выдаёт промокод — без лимитов один человек
может слать сообщения сотнями или «покупать» товары, не покупая их.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Client, Message, Purchase

AI_LIMIT_TEXT = {
    "minute": "Я не успеваю за вами 🙂 Подождите, пожалуйста, минутку и напишите ещё раз.",
    "day": "На сегодня мы с вами обсудили очень много. Напишите, пожалуйста, завтра — с радостью продолжу!",
}


async def ai_limit_exceeded(session: AsyncSession, client: Client) -> str | None:
    """«minute» или «day», если клиент исчерпал лимит сообщений к AI, иначе None.

    Считаем сообщения клиента, на которые AI уже отвечал. Сравниваем со временем базы (now()),
    потому что created_at проставляет сама база.
    """
    settings = get_settings()
    per_minute, per_day = settings.ai_messages_per_minute, settings.ai_messages_per_day
    if not per_minute and not per_day:
        return None

    last_minute, last_day = (
        await session.execute(
            select(
                func.count().filter(Message.created_at > func.now() - timedelta(minutes=1)),
                func.count(),
            ).where(
                Message.client_id == client.id,
                Message.role == "user",
                Message.created_at > func.now() - timedelta(days=1),
            )
        )
    ).one()
    if per_day and last_day >= per_day:
        return "day"
    if per_minute and last_minute >= per_minute:
        return "minute"
    return None


async def is_repeat_scan(session: AsyncSession, client: Client, product_id: int) -> bool:
    """Клиент уже сканировал QR этого товара недавно — новой покупкой это не считаем."""
    days = get_settings().qr_repeat_days
    if not days:
        return False
    found = await session.scalar(
        select(Purchase.id)
        .where(
            Purchase.client_id == client.id,
            Purchase.product_id == product_id,
            Purchase.created_at > func.now() - timedelta(days=days),
        )
        .limit(1)
    )
    return found is not None


async def qr_limit_exceeded(session: AsyncSession, client: Client) -> bool:
    """Клиент отсканировал за сутки больше QR, чем разрешено."""
    limit = get_settings().qr_scans_per_day
    if not limit:
        return False
    scans = await session.scalar(
        select(func.count())
        .select_from(Purchase)
        .where(Purchase.client_id == client.id, Purchase.created_at > func.now() - timedelta(days=1))
    )
    return (scans or 0) >= limit
