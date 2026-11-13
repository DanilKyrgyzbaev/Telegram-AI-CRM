import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import Select, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Broadcast, Client

logger = logging.getLogger(__name__)

# Лимит Telegram — около 30 сообщений в секунду, держим запас
SEND_DELAY = 1 / 25


def utcnow() -> datetime:
    """Текущее время в UTC без tzinfo — в таком виде время хранится в базе."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_db_time(value: datetime) -> datetime:
    """Переводит время в UTC без tzinfo. Время без часового пояса считается UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def format_local(value: datetime) -> str:
    """Время из базы (UTC) → строка в часовом поясе админа."""
    return value.replace(tzinfo=timezone.utc).astimezone(local_tz()).strftime("%d.%m.%Y %H:%M")


def recipients_query(source: str | None) -> Select[tuple[Client]]:
    query = select(Client).where(Client.is_blocked.is_(False))
    if source:
        query = query.where(Client.source == source)
    return query


async def _send(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except TelegramRetryAfter as e:
        # Telegram просит подождать — ждём и пробуем ещё раз
        await asyncio.sleep(e.retry_after)
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def run_broadcast(broadcast_id: int) -> None:
    """Отправляет рассылку всем активным клиентам. Запускается в фоне."""
    bot = Bot(get_settings().bot_token)
    try:
        async with SessionLocal() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            broadcast.status = "sending"
            await session.commit()

            clients = (await session.scalars(recipients_query(broadcast.source))).all()

            for client in clients:
                try:
                    await _send(bot, client.telegram_id, broadcast.text)
                    broadcast.sent_count += 1
                except TelegramForbiddenError:
                    client.is_blocked = True
                    broadcast.failed_count += 1
                except TelegramAPIError:
                    logger.exception("Broadcast %s: failed to send to %s", broadcast_id, client.telegram_id)
                    broadcast.failed_count += 1
                await asyncio.sleep(SEND_DELAY)

            broadcast.status = "done"
            broadcast.finished_at = utcnow()
            await session.commit()
    finally:
        await bot.session.close()


async def run_and_report(bot: Bot, chat_ids: Iterable[int], broadcast_id: int) -> None:
    """Отправляет рассылку и присылает итог админам в Telegram."""
    try:
        await run_broadcast(broadcast_id)
    except Exception:
        logger.exception("Broadcast %s crashed", broadcast_id)
        report = f"⚠️ Рассылка #{broadcast_id} прервалась с ошибкой, подробности в логах."
    else:
        async with SessionLocal() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
        report = (
            f"✅ Рассылка #{broadcast_id} завершена.\n"
            f"Доставлено: {broadcast.sent_count}\n"
            f"Не доставлено: {broadcast.failed_count}"
        )

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, report)
        except TelegramAPIError:
            logger.exception("Не удалось отправить отчёт о рассылке админу %s", chat_id)
