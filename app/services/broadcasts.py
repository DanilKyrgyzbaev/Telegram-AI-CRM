import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Broadcast, Client

logger = logging.getLogger(__name__)

# Лимит Telegram — около 30 сообщений в секунду, держим запас
SEND_DELAY = 1 / 25
# Сколько клиентов читаем из базы за раз
BATCH_SIZE = 200
# Рассылка не обновляла «пульс» дольше этого времени — процесс, который её вёл, упал
STALE_AFTER = timedelta(minutes=5)
# Во время долгого ожидания (Telegram попросил притормозить) обновляем «пульс» не реже этого, секунд
HEARTBEAT_INTERVAL = 30


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


def format_local(value: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Время из базы (UTC) → строка в часовом поясе админа."""
    return value.replace(tzinfo=timezone.utc).astimezone(local_tz()).strftime(fmt)


def recipients_query(source: str | None, client_id: int | None = None) -> Select[tuple[Client]]:
    # Рассылки — только в Telegram: Instagram запрещает писать клиенту позже чем через 24 часа после его сообщения
    query = select(Client).where(Client.is_blocked.is_(False), Client.telegram_id.is_not(None))
    if source:
        query = query.where(Client.source == source)
    if client_id is not None:
        query = query.where(Client.id == client_id)
    return query


async def _wait(session: AsyncSession, broadcast: Broadcast, seconds: float) -> None:
    """Ждёт, обновляя «пульс» рассылки, чтобы её не сочли оборванной и не запустили второй раз."""
    while seconds > 0:
        step = min(seconds, HEARTBEAT_INTERVAL)
        await asyncio.sleep(step)
        seconds -= step
        broadcast.updated_at = utcnow()
        await session.commit()


async def _send(bot: Bot, session: AsyncSession, broadcast: Broadcast, chat_id: int) -> None:
    try:
        await bot.send_message(chat_id, broadcast.text, parse_mode="HTML")
    except TelegramRetryAfter as e:
        # Telegram просит подождать — ждём и пробуем ещё раз
        await _wait(session, broadcast, e.retry_after)
        await bot.send_message(chat_id, broadcast.text, parse_mode="HTML")


async def _claim(session: AsyncSession, broadcast_id: int) -> Broadcast | None:
    """Атомарно берёт рассылку в работу: pending → sending. None — её уже ведёт другой процесс."""
    claimed = await session.scalar(
        update(Broadcast)
        .where(Broadcast.id == broadcast_id, Broadcast.status == "pending")
        .values(status="sending", updated_at=utcnow())
        .returning(Broadcast.id)
    )
    await session.commit()
    if claimed is None:
        return None
    return await session.get(Broadcast, broadcast_id)


async def run_broadcast(broadcast_id: int) -> bool:
    """Отправляет рассылку всем активным клиентам. Запускается в фоне.

    Прогресс сохраняется после каждого сообщения, поэтому прерванная рассылка (перезапуск,
    сбой) продолжается с того клиента, на котором остановилась, а не начинается заново.
    False — рассылку уже отправляет другой процесс, здесь ничего не сделано.
    """
    bot = Bot(get_settings().bot_token)
    try:
        async with SessionLocal() as session:
            broadcast = await _claim(session, broadcast_id)
            if broadcast is None:
                return False

            while True:
                clients = (
                    await session.scalars(
                        recipients_query(broadcast.source, broadcast.client_id)
                        .where(Client.id > broadcast.last_client_id)
                        .order_by(Client.id)
                        .limit(BATCH_SIZE)
                    )
                ).all()
                if not clients:
                    break

                for client in clients:
                    try:
                        await _send(bot, session, broadcast, client.telegram_id)
                        broadcast.sent_count += 1
                    except TelegramForbiddenError:
                        client.is_blocked = True
                        broadcast.failed_count += 1
                    except TelegramAPIError:
                        logger.exception("Broadcast %s: failed to send to %s", broadcast_id, client.telegram_id)
                        broadcast.failed_count += 1
                    broadcast.last_client_id = client.id
                    broadcast.updated_at = utcnow()
                    await session.commit()
                    await asyncio.sleep(SEND_DELAY)

            broadcast.status = "done"
            broadcast.finished_at = utcnow()
            await session.commit()
            return True
    finally:
        await bot.session.close()


async def run_and_report(bot: Bot, chat_ids: Iterable[int], broadcast_id: int) -> None:
    """Отправляет рассылку и присылает итог админам в Telegram."""
    try:
        if not await run_broadcast(broadcast_id):
            return
    except Exception:
        logger.exception("Broadcast %s crashed", broadcast_id)
        report = (
            f"⚠️ Рассылка #{broadcast_id} прервалась с ошибкой, подробности в логах.\n"
            "Бот сам продолжит её с места остановки в течение нескольких минут."
        )
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
