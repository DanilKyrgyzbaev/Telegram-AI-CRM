"""Сводка для главной страницы админки: цифры за сегодня и неделю и то, что ждёт решения админа."""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChannelPost, Client, Message, Product, Purchase
from app.services.broadcasts import local_tz, utcnow
from app.services.promo import current_promo

# Как источник клиента выглядит в сводке
SOURCE_LABELS = {"qr": "QR с упаковки", "site": "Сайт", "app": "Каталог в Telegram", "instagram": "Instagram"}
LATEST_MESSAGES = 6


@dataclass
class Dashboard:
    new_clients_today: int
    new_clients_week: int
    client_messages_today: int
    ai_replies_today: int
    qr_scans_today: int
    qr_scans_week: int
    published_week: int
    sources_week: list[tuple[str, int]]
    drafts: list[ChannelPost]
    failed: list[ChannelPost]
    scheduled: list[ChannelPost]
    latest_messages: list[tuple[Message, Client]]
    warnings: list[str] = field(default_factory=list)


def _today_start_utc() -> datetime:
    """Полночь сегодняшнего дня по часовому поясу админа — в UTC, как время хранится в базе."""
    midnight = datetime.combine(datetime.now(local_tz()).date(), time(), tzinfo=local_tz())
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


async def _count(session: AsyncSession, query) -> int:
    return await session.scalar(query) or 0


def _new_clients(since: datetime):
    return select(func.count(Client.id)).where(Client.created_at >= since)


def _messages(role: str, since: datetime):
    return select(func.count(Message.id)).where(Message.role == role, Message.created_at >= since)


def _scans(since: datetime):
    return select(func.count(Purchase.id)).where(Purchase.created_at >= since)


def _posts(status: str):
    return select(ChannelPost).where(ChannelPost.status == status)


async def build(session: AsyncSession) -> Dashboard:
    today = _today_start_utc()
    week = utcnow() - timedelta(days=7)

    source = func.coalesce(Client.source, "")
    rows = await session.execute(
        select(source, func.count(Client.id)).where(Client.created_at >= week).group_by(source)
        .order_by(func.count(Client.id).desc())
    )
    sources = [(SOURCE_LABELS.get(name, name or "Напрямую"), count) for name, count in rows]
    latest = await session.execute(
        select(Message, Client).join(Client, Client.id == Message.client_id)
        .where(Message.role == "user").order_by(Message.id.desc()).limit(LATEST_MESSAGES)
    )

    dashboard = Dashboard(
        new_clients_today=await _count(session, _new_clients(today)),
        new_clients_week=await _count(session, _new_clients(week)),
        client_messages_today=await _count(session, _messages("user", today)),
        ai_replies_today=await _count(session, _messages("assistant", today)),
        qr_scans_today=await _count(session, _scans(today)),
        qr_scans_week=await _count(session, _scans(week)),
        published_week=await _count(session, select(func.count(ChannelPost.id)).where(
            ChannelPost.status == "published", ChannelPost.published_at >= week
        )),
        sources_week=sources,
        drafts=list(await session.scalars(_posts("draft").order_by(ChannelPost.id.desc()))),
        failed=list(await session.scalars(_posts("failed").order_by(ChannelPost.id.desc()))),
        scheduled=list(await session.scalars(_posts("scheduled").order_by(ChannelPost.scheduled_at))),
        latest_messages=list(latest.tuples()),
    )

    if await current_promo(session) is None:
        dashboard.warnings.append("Нет действующего промокода — после скана QR покупатели не получат скидку.")
    without_sizes = await _count(session, select(func.count(Product.id)).where(
        Product.is_active, Product.wb_article.is_not(None), Product.size_chart == ""
    ))
    if without_sizes:
        dashboard.warnings.append(
            f"У {without_sizes} товаров нет таблицы размеров с WB — бот подберёт размер только примерно."
        )
    return dashboard
