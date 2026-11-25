"""Ежедневный контент-план: каждое утро AI готовит пост и сторис, админ одобряет их в боте."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.posts import RUBRIC_BY_WEEKDAY, RUBRICS
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


async def create_day_drafts(session: AsyncSession, day: date) -> list[int]:
    """Создаёт записи поста и сторис на день (без текста — его потом пишет AI). Возвращает их ID."""
    settings = get_settings()
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
    return [post.id, story.id]


async def create_daily_drafts(bot: Bot, day: date | None = None) -> list[int]:
    """Создаёт пост и сторис на день и запускает AI. Возвращает ID созданных черновиков."""
    day = day or datetime.now(local_tz()).date()
    async with SessionLocal() as session:
        ids = await create_day_drafts(session, day)
    for post_id in ids:
        await generate(bot, post_id)
    return ids


def _midnight_utc(day: date) -> datetime:
    """Начало дня по часовому поясу админа — в UTC, как время хранится в базе."""
    return datetime.combine(day, time(), tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)


def _local_day(moment: datetime) -> date:
    return moment.replace(tzinfo=timezone.utc).astimezone(local_tz()).date()


# К какому дню относится пост: когда вышел, иначе когда выйдет, иначе когда создан
_post_moment = func.coalesce(
    ChannelPost.published_at, ChannelPost.scheduled_at, ChannelPost.planned_at, ChannelPost.created_at
)


async def _posts_between(session: AsyncSession, start: date, end: date) -> list[ChannelPost]:
    """Посты и сторис за дни [start, end)."""
    rows = await session.scalars(
        select(ChannelPost)
        .where(_post_moment >= _midnight_utc(start), _post_moment < _midnight_utc(end))
        .order_by(_post_moment)
    )
    return list(rows)


async def has_plan(session: AsyncSession, day: date) -> bool:
    """Есть ли уже пост контент-плана на этот день — например, админ подготовил его заранее."""
    posts = await _posts_between(session, day, day + timedelta(days=1))
    return any(post.rubric for post in posts)


@dataclass
class PlanDay:
    day: date
    rubric: str  # Рубрика дня по контент-плану
    posts: list[ChannelPost]
    is_today: bool
    is_past: bool

    @property
    def can_prepare(self) -> bool:
        """Черновики можно подготовить на сегодня и вперёд, если их ещё нет."""
        return not self.is_past and not any(post.rubric for post in self.posts)


async def week_plan(session: AsyncSession, monday: date) -> list[PlanDay]:
    """Календарь недели: рубрика каждого дня и посты, которые на него приходятся."""
    posts = await _posts_between(session, monday, monday + timedelta(days=7))
    moments = {post.id: post.published_at or post.scheduled_at or post.planned_at or post.created_at for post in posts}
    today = datetime.now(local_tz()).date()
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        days.append(PlanDay(
            day=day,
            rubric=RUBRICS[RUBRIC_BY_WEEKDAY[day.weekday()]][0],
            posts=[post for post in posts if _local_day(moments[post.id]) == day],
            is_today=day == today,
            is_past=day < today,
        ))
    return days


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
        # Админ мог подготовить черновики на сегодня заранее — из календаря в админке
        prepared = await has_plan(session, now.date())
        # Отмечаем день до генерации: если AI упадёт, черновики не будут создаваться каждые 30 секунд
        if mark is None:
            session.add(AppSetting(key=LAST_RUN_KEY, value=today))
        else:
            mark.value = today
        await session.commit()
    if prepared:
        return
    logger.info("Content plan: готовлю черновики на %s", today)
    await create_daily_drafts(bot, now.date())
