"""Публичный сайт-каталог магазина: карточки товаров с кнопками на Wildberries."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Product
from app.services.qr import bot_username

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
STATIC = Path(__file__).parent / "static"
# Картинки бренда из корня сайта: логотип (тёмный и светлый — для тёмного меню админки), значок вкладки, иконка для iPhone
BRAND_FILES = ("logo.png", "logo-light.png", "favicon.png", "apple-touch-icon.png")
# Метка кампании для ссылки на бота: клиенты с сайта видны в CRM с источником «site»
BOT_START_PARAM = "site"
SIMILAR_LIMIT = 4
# Дата текущей редакции политики конфиденциальности — менять при правке текста
PRIVACY_UPDATED = "25 ноября 2026 г."


def _price(value) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


templates.env.filters["price"] = _price


async def _bot_url() -> str | None:
    # Ссылка на бота не должна ронять сайт, если Telegram недоступен
    try:
        return f"https://t.me/{await bot_username()}?start={BOT_START_PARAM}"
    except Exception:
        logger.exception("Не удалось узнать username бота")
        return None


async def _context(request: Request, **extra) -> dict:
    settings = get_settings()
    return {
        "request": request,
        "shop": settings.shop_name or "Магазин",
        "shop_url": settings.shop_url,
        "channel_url": settings.channel_url,
        "instagram_url": settings.instagram_url,
        "owner": settings.shop_legal_name or settings.shop_name or "Магазин",
        "contact_email": settings.contact_email,
        "bot_url": await _bot_url(),
        **extra,
    }


def _active() -> Select:
    return select(Product).where(Product.is_active).order_by(Product.category, Product.name)


@router.get("/", response_class=HTMLResponse)
async def catalog(
    request: Request, category: str | None = None, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    products = list(await session.scalars(_active()))
    categories = sorted({p.category for p in products if p.category})
    if category:
        products = [p for p in products if p.category == category]
    return templates.TemplateResponse(
        request,
        "catalog.html",
        await _context(request, products=products, categories=categories, current=category),
    )


@router.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(
    request: Request, product_id: int, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    product = await session.get(Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404)
    similar = list(
        await session.scalars(
            _active().where(Product.category == product.category, Product.id != product.id).limit(SIMILAR_LIMIT)
        )
    )
    return templates.TemplateResponse(
        request, "product.html", await _context(request, product=product, similar=similar)
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "privacy.html", await _context(request, updated=PRIVACY_UPDATED))


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "data_deletion.html", await _context(request))


def _brand_file(name: str):
    async def serve() -> FileResponse:
        return FileResponse(STATIC / name, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    return serve


for _name in BRAND_FILES:
    router.add_api_route(f"/{_name}", _brand_file(_name), methods=["GET"], include_in_schema=False)
