"""Публичный сайт-каталог магазина: карточки товаров с кнопками на Wildberries."""

import io
import logging
from pathlib import Path

import segno

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Product
from app.services.qr import APP_START_PARAM, ASK_START_PREFIX, bot_username

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
STATIC = Path(__file__).parent / "static"
# Картинки бренда из корня сайта: логотип (тёмный и светлый — для тёмного меню админки), значок вкладки,
# иконка для iPhone, QR Instagram для подвала (вырезан из brand/instagram_qr_code.jpg)
BRAND_FILES = ("logo.png", "logo-light.png", "favicon.png", "apple-touch-icon.png", "instagram-qr.png")
QR_COLOR = "#1d1a17"
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


# Telegram Mini App: каталог внутри Telegram, открывается кнопкой «Каталог» в боте
async def _ask_url(start: str) -> str | None:
    try:
        return f"https://t.me/{await bot_username()}?start={start}"
    except Exception:
        logger.exception("Не удалось узнать username бота")
        return None


@router.get("/app", response_class=HTMLResponse)
async def app_catalog(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    products = list(await session.scalars(_active()))
    categories = sorted({p.category for p in products if p.category})
    return templates.TemplateResponse(
        request, "app/catalog.html",
        await _context(request, products=products, categories=categories, bot_ask_url=await _ask_url(APP_START_PARAM)),
    )


@router.get("/app/product/{product_id}", response_class=HTMLResponse)
async def app_product(request: Request, product_id: int, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    product = await session.get(Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404)
    similar = list(
        await session.scalars(
            _active().where(Product.category == product.category, Product.id != product.id).limit(SIMILAR_LIMIT)
        )
    )
    return templates.TemplateResponse(
        request, "app/product.html",
        await _context(request, product=product, similar=similar, bot_ask_url=await _ask_url(f"{ASK_START_PREFIX}{product.id}")),
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "privacy.html", await _context(request, updated=PRIVACY_UPDATED))


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "data_deletion.html", await _context(request))


@router.get("/qr/telegram.svg", include_in_schema=False)
async def telegram_qr() -> Response:
    """QR на бота с меткой «site» — посетители с компьютера сканируют его телефоном."""
    url = await _bot_url()
    if url is None:
        raise HTTPException(status_code=404)
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="svg", scale=8, border=2, dark=QR_COLOR, light="#ffffff", xmldecl=False)
    return Response(buffer.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


def _brand_file(name: str):
    async def serve() -> FileResponse:
        return FileResponse(STATIC / name, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    return serve


for _name in BRAND_FILES:
    router.add_api_route(f"/{_name}", _brand_file(_name), methods=["GET"], include_in_schema=False)
