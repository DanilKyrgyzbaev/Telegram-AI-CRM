from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int
    username: str | None
    full_name: str
    source: str | None
    subscribed: bool
    is_blocked: bool
    created_at: datetime


class ProductIn(BaseModel):
    name: str
    category: str | None = None
    description: str = ""
    wb_article: int | None = None
    price: Decimal
    is_active: bool = True


class ProductOut(ProductIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class SourceStat(BaseModel):
    source: str | None
    clients: int


class ProductScanStat(BaseModel):
    product_id: int
    name: str
    scans: int
    clients: int


class Stats(BaseModel):
    total_clients: int
    subscribed: int
    by_source: list[SourceStat]
    # Сканирования QR с упаковок по товарам
    qr_scans: list[ProductScanStat]


class PromoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    percent: int
    product_id: int | None
    expires_at: datetime | None


class BroadcastIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    source: str | None = None
    # ISO 8601, например 2026-12-25T18:00:00+03:00. Без часового пояса считается UTC.
    # Не задано — отправить сразу
    scheduled_at: datetime | None = None


class BroadcastOut(BroadcastIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    sent_count: int
    failed_count: int
    created_at: datetime
    finished_at: datetime | None
