"""Публичные файлы без ключа API: фото товаров и картинки сторис для Instagram и сайта."""

from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import ChannelPost, Product
from app.services.story_image import story_image
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


@router.get("/media/stories/{post_id}.jpg")
async def story_picture(post_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    """Картинка сторис: Instagram скачивает её при публикации."""
    post = await session.get(ChannelPost, post_id)
    picture = await story_image(post) if post and post.kind == "story" else None
    if picture is None:
        raise HTTPException(status_code=404)
    return Response(picture, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
