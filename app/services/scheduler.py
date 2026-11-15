import asyncio
import logging

from aiogram import Bot
from sqlalchemy import update

from app.config import get_settings
from app.db import SessionLocal
from app.models import Broadcast
from app.services.broadcasts import STALE_AFTER, run_and_report, utcnow

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # секунд


async def run_scheduler(bot: Bot) -> None:
    """Раз в CHECK_INTERVAL секунд запускает рассылки, время которых наступило."""
    while True:
        try:
            await _run_due_broadcasts(bot)
        except Exception:
            logger.exception("Scheduler iteration failed")
        await asyncio.sleep(CHECK_INTERVAL)


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
