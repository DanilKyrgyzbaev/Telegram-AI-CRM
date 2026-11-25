"""Ежедневный контент-план: каждое утро AI готовит пост и сторис, админ одобряет их в боте."""

import logging
from datetime import date, datetime, time, timezone

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.posts import RUBRIC_BY_WEEKDAY
from app.config import get_settings
from app.db import SessionLocal
from app.models import AppSetting, ChannelPost, Product
from app.services.broadcasts import local_tz, utcnow
from app.services.channel_posts import generate
from app.services.promo import current_promo

logger = logging.getLogger(__name__)

# Дата (по часовому поясу админа), за которую черновики уже подготовлены — чтобы не повторять после перезапуска
LAST_RUN_KEY = "content_plan_date"


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _planned_utc(day: date, at: str) -> datetime | None:
    """Время публикации сегодня в UTC; None — оно уже прошло, останется только «Опубликовать сейчас»."""
    moment = datetime.combine(day, _parse_time(at), tzinfo=local_tz())
    utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return utc if utc > utcnow() else None


async def _products_by_freshness(session: AsyncSession) -> list[Product]:
    """Товары с фото на WB: сначала те, о которых дольше всего (или никогда) не писали."""
    last_featured = (
        select(ChannelPost.product_id, func.max(ChannelPost.created_at).label("last"))
        .group_by(ChannelPost.product_id)
        .subquery()
    )
    rows = await session.execute(
        select(Product)
        .outerjoin(last_featured, last_featured.c.product_id == Product.id)
        .where(Product.is_active, Product.wb_article.is_not(None))
        .order_by(last_featured.c.last.asc().nulls_first(), func.random())
    )
    return list(rows.scalars())


async def create_daily_drafts(bot: Bot, day: date | None = None) -> list[int]:
    """Создаёт пост и сторис на день и запускает AI. Возвращает ID созданных черновиков."""
    settings = get_settings()
    day = day or datetime.now(local_tz()).date()
    async with SessionLocal() as session:
        products = await _products_by_freshness(session)
        if not products:
            logger.warning("Content plan: нет активных товаров с артикулом WB")
            return []
        rubric = RUBRIC_BY_WEEKDAY[day.weekday()]
        discount = await current_promo(session) if rubric == "promo" else None
        if rubric == "promo" and discount is None:
            rubric = "spotlight"
        post = ChannelPost(
            kind="post", rubric=rubric, status="generating", product_id=products[0].id,
            discount_id=discount.id if discount else None,
            planned_at=_planned_utc(day, settings.content_post_time),
        )
        # Сторис — про другой товар, чтобы за день показать два
        story = ChannelPost(
            kind="story", rubric="story", status="generating", product_id=products[min(1, len(products) - 1)].id,
            planned_at=_planned_utc(day, settings.content_story_time),
        )
        session.add_all([post, story])
        await session.commit()
        ids = [post.id, story.id]
    for post_id in ids:
        await generate(bot, post_id)
    return ids


async def run_if_due(bot: Bot) -> None:
    """Вызывается планировщиком: раз в день после CONTENT_DRAFTS_TIME готовит черновики."""
    settings = get_settings()
    if not settings.content_plan_enabled:
        return
    now = datetime.now(local_tz())
    if now.time() < _parse_time(settings.content_drafts_time):
        return
    today = now.date().isoformat()
    async with SessionLocal() as session:
        mark = await session.get(AppSetting, LAST_RUN_KEY)
        if mark and mark.value == today:
            return
        # Отмечаем день до генерации: если AI упадёт, черновики не будут создаваться каждые 30 секунд
        if mark is None:
            session.add(AppSetting(key=LAST_RUN_KEY, value=today))
        else:
            mark.value = today
        await session.commit()
    logger.info("Content plan: готовлю черновики на %s", today)
    await create_daily_drafts(bot, now.date())
