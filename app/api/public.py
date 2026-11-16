"""Публичные страницы без ключа API: фото товаров для Instagram и политика конфиденциальности для Meta."""

import html
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Product
from app.services.wb_images import product_photo

router = APIRouter()

# Instagram скачивает фото при публикации и для карточек в Direct — не ходим каждый раз на WB
_photos: OrderedDict[int, bytes] = OrderedDict()
PHOTOS_LIMIT = 100


@router.get("/media/products/{product_id}.jpg")
async def product_image(product_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    if product_id not in _photos:
        product = await session.get(Product, product_id)
        photo = await product_photo(product.wb_article) if product and product.wb_article else None
        if photo is None:
            raise HTTPException(status_code=404)
        _photos[product_id] = photo
        if len(_photos) > PHOTOS_LIMIT:
            _photos.popitem(last=False)
    return Response(_photos[product_id], media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.6;color:#222}}</style>
</head><body><h1>{title}</h1>{body}</body></html>"""
    )


def _shop() -> str:
    return html.escape(get_settings().shop_name or "Магазин")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    shop = _shop()
    return _page(
        f"Политика конфиденциальности {shop}",
        f"""
<p>{shop} использует Telegram-бота и Instagram Direct, чтобы отвечать покупателям: консультировать по товарам,
рекомендовать модели и выдавать промокоды. Ответы готовит AI-ассистент.</p>
<h2>Какие данные мы получаем</h2>
<ul>
<li>ID и имя пользователя в Telegram или Instagram, имя профиля;</li>
<li>текст сообщений и комментариев, которые вы нам отправили;</li>
<li>товары, QR-коды которых вы отсканировали.</li>
</ul>
<h2>Зачем</h2>
<p>Только чтобы отвечать на ваши вопросы, подбирать товары и сообщать об акциях магазина.
Мы не продаём и не передаём данные третьим лицам, кроме сервиса AI (Anthropic), который формирует ответы.</p>
<h2>Хранение и удаление</h2>
<p>Данные хранятся на защищённом сервере. Чтобы удалить их, напишите нам «удалите мои данные»
в Telegram-бот или в Direct — мы удалим историю переписки и профиль в течение 30 дней.
Подробнее — на странице <a href="/data-deletion">удаления данных</a>.</p>
""",
    )


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion() -> HTMLResponse:
    return _page(
        "Удаление данных",
        f"""
<p>Чтобы удалить ваши данные из CRM {_shop()}, напишите «удалите мои данные» в Instagram Direct
или в Telegram-бот магазина. Мы удалим профиль, историю переписки и покупки в течение 30 дней
и подтвердим удаление ответным сообщением.</p>
""",
    )
