from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import BroadcastIn, BroadcastOut
from app.db import get_session
from app.models import Broadcast
from app.services.broadcasts import run_broadcast, to_db_time, utcnow

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])


@router.post("", response_model=BroadcastOut, status_code=202)
async def create_broadcast(
    data: BroadcastIn, background: BackgroundTasks, session: AsyncSession = Depends(get_session)
):
    broadcast = Broadcast(text=data.text, source=data.source)
    if data.scheduled_at is not None:
        scheduled_at = to_db_time(data.scheduled_at)
        if scheduled_at <= utcnow():
            raise HTTPException(status_code=422, detail="scheduled_at must be in the future")
        # Отправит планировщик в процессе бота
        broadcast.scheduled_at = scheduled_at
        broadcast.status = "scheduled"

    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)
    if data.scheduled_at is None:
        background.add_task(run_broadcast, broadcast.id)
    return broadcast


@router.get("", response_model=list[BroadcastOut])
async def list_broadcasts(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Broadcast).order_by(Broadcast.id.desc()))).all()


@router.get("/{broadcast_id}", response_model=BroadcastOut)
async def get_broadcast(broadcast_id: int, session: AsyncSession = Depends(get_session)):
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    return broadcast


@router.delete("/{broadcast_id}", status_code=204)
async def cancel_broadcast(broadcast_id: int, session: AsyncSession = Depends(get_session)):
    """Отменяет отложенную рассылку, пока она не началась."""
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    if broadcast.status != "scheduled":
        raise HTTPException(status_code=409, detail="Only scheduled broadcasts can be cancelled")
    await session.delete(broadcast)
    await session.commit()
