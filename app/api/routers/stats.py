from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ProductScanStat, SourceStat, Stats
from app.db import get_session
from app.models import Client, Product, Purchase

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=Stats)
async def get_stats(session: AsyncSession = Depends(get_session)):
    total = await session.scalar(select(func.count(Client.id)))
    subscribed = await session.scalar(select(func.count(Client.id)).where(Client.subscribed))
    rows = await session.execute(select(Client.source, func.count(Client.id)).group_by(Client.source))
    scans = await session.execute(
        select(Product.id, Product.name, func.count(Purchase.id), func.count(distinct(Purchase.client_id)))
        .join(Purchase)
        .group_by(Product.id)
        .order_by(func.count(Purchase.id).desc())
    )
    return Stats(
        total_clients=total or 0,
        subscribed=subscribed or 0,
        by_source=[SourceStat(source=source, clients=count) for source, count in rows],
        qr_scans=[
            ProductScanStat(product_id=pid, name=name, scans=scan_count, clients=client_count)
            for pid, name, scan_count, client_count in scans
        ],
    )
