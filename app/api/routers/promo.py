from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PromoOut
from app.db import get_session
from app.services.promo import current_promo

router = APIRouter(prefix="/promo", tags=["promo"])


@router.get("/current", response_model=PromoOut)
async def get_current_promo(session: AsyncSession = Depends(get_session)):
    """Промокод WB, который бот сейчас выдаёт покупателям."""
    promo = await current_promo(session)
    if promo is None:
        raise HTTPException(status_code=404, detail="No active promo code")
    return promo
