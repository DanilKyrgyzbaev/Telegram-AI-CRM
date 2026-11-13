from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Discount
from app.services.broadcasts import format_local, utcnow


def promo_status(discount: Discount) -> str:
    if not discount.is_active:
        return "выключен"
    if discount.expires_at is not None and discount.expires_at <= utcnow():
        return "просрочен"
    return "активен"


def format_expires(discount: Discount) -> str:
    return format_local(discount.expires_at)[:10] if discount.expires_at else "бессрочно"


async def current_promo(session: AsyncSession) -> Discount | None:
    """Промокод WB, который сейчас выдаём покупателям: самый новый из активных."""
    return await session.scalar(
        select(Discount)
        .where(Discount.is_active, or_(Discount.expires_at.is_(None), Discount.expires_at > utcnow()))
        .order_by(Discount.id.desc())
        .limit(1)
    )
