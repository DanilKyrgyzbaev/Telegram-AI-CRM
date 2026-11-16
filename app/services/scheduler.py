import asyncio
import logging

from aiogram import Bot
from sqlalchemy import select, update

from app.config import get_settings
from app.db import SessionLocal
from app.instagram.api import refresh_token_if_needed
from app.models import Broadcast, ChannelPost
from app.services.broadcasts import STALE_AFTER, run_and_report, utcnow
from app.services.channel_posts import publish_and_report

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # секунд


async def run_scheduler(bot: Bot) -> None:
    """Раз в CHECK_INTERVAL секунд публикует посты и запускает рассылки, время которых наступило."""
    while True:
        try:
            # Посты раньше рассылок: долгая рассылка не должна задерживать публикацию
            await _publish_due_posts(bot)
            await _run_due_broadcasts(bot)
            # Сама проверяет, пора ли (раз в неделю): токен Instagram живёт 60 дней
            await refresh_token_if_needed()
        except Exception:
            logger.exception("Scheduler iteration failed")
        await asyncio.sleep(CHECK_INTERVAL)


async def _publish_due_posts(bot: Bot) -> None:
    async with SessionLocal() as session:
        due_ids = (
            await session.scalars(
                select(ChannelPost.id).where(
                    ChannelPost.status == "scheduled", ChannelPost.scheduled_at <= utcnow()
                )
            )
        ).all()
    for post_id in due_ids:
        logger.info("Publishing channel post %s", post_id)
        await publish_and_report(bot, post_id, ("scheduled",))


async def _run_due_broadcasts(bot: Bot) -> None:
    now = utcnow()
    async with SessionLocal() as session:
        # Атомарно «забираем» рассылки: даже при двух запущенных ботах каждая уйдёт один раз
        due_ids = (
            await session.scalars(
                update(Broadcast)
                .where(Broadcast.status == "scheduled", Broadcast.scheduled_at <= now)
                .values(status="pending", updated_at=now)
                .returning(Broadcast.id)
            )
        ).all()
        # Оборванные рассылки (процесс упал или был перезапущен посреди отправки) —
        # возвращаем в очередь, они продолжатся с места остановки
        stale_ids = (
            await session.scalars(
                update(Broadcast)
                .where(Broadcast.status.in_(("pending", "sending")), Broadcast.updated_at < now - STALE_AFTER)
                .values(status="pending", updated_at=now)
                .returning(Broadcast.id)
            )
        ).all()
        await session.commit()

    for broadcast_id in stale_ids:
        logger.warning("Resuming interrupted broadcast %s", broadcast_id)
    for broadcast_id in [*due_ids, *stale_ids]:
        logger.info("Starting broadcast %s", broadcast_id)
        await run_and_report(bot, get_settings().admin_ids, broadcast_id)
