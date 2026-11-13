from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ClientOut
from app.db import get_session
from app.models import Client

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
async def list_clients(limit: int = 50, offset: int = 0, session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Client).order_by(Client.id.desc()).limit(limit).offset(offset))
    return result.all()
