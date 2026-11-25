"""Instagram API: Direct, ответы на комментарии, публикация постов."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import aiohttp

from app.config import get_settings
from app.db import SessionLocal
from app.models import AppSetting, Product
from app.services.broadcasts import utcnow

logger = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)
# Ограничения Instagram: текст сообщения в Direct и подпись к посту
MESSAGE_LIMIT = 1000
CAPTION_LIMIT = 2200
# В карточке-карусели не больше 10 товаров
CARDS_LIMIT = 10
# Долгоживущий токен входа через Instagram действует 60 дней — продлеваем заранее
TOKEN_REFRESH_EVERY = timedelta(days=7)
# Только токены этого хоста истекают и продлеваются; токен системного пользователя бессрочный
INSTAGRAM_LOGIN_HOST = "graph.instagram.com"
TOKEN_KEY = "instagram_access_token"


class InstagramError(Exception):
    pass


async def access_token() -> str:
    """Актуальный токен: обновлённый (из базы) или исходный из .env."""
    async with SessionLocal() as session:
        stored = await session.get(AppSetting, TOKEN_KEY)
    return stored.value if stored else get_settings().instagram_access_token


async def _request(method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> dict[str, Any]:
    settings = get_settings()
    url = f"https://{settings.instagram_graph_host}/{settings.instagram_api_version}/{path}"
    headers = {"Authorization": f"Bearer {await access_token()}"}
    async with aiohttp.ClientSession(timeout=TIMEOUT) as http:
        async with http.request(method, url, params=params, json=json, headers=headers) as response:
            data = await response.json(content_type=None)
    if response.status >= 400 or "error" in data:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        raise InstagramError(error.get("message") or f"HTTP {response.status}")
    return data


def _account() -> str:
    return get_settings().instagram_account_id


def product_image_url(product: Product) -> str | None:
    """Публичная ссылка на фото товара с нашего сервера — Instagram скачивает картинку сам."""
    domain = get_settings().domain
    if not domain or not product.wb_article:
        return None
    return f"https://{domain}/media/products/{product.id}.jpg"


async def user_profile(igsid: str) -> dict[str, Any]:
    """Имя и username собеседника; пустой словарь, если Instagram их не отдал."""
    try:
        return await _request("GET", igsid, params={"fields": "name,username"})
    except (InstagramError, aiohttp.ClientError, asyncio.TimeoutError):
        logger.warning("Instagram: не удалось получить профиль %s", igsid)
        return {}


async def send_text(igsid: str, text: str) -> None:
    await _request("POST", f"{_account()}/messages", json={
        "recipient": {"id": igsid},
        "message": {"text": text[:MESSAGE_LIMIT]},
    })


async def send_products(igsid: str, products: Sequence[Product]) -> None:
    """Карусель карточек: фото, название, цена и кнопка на Wildberries."""
    elements = []
    for p in products[:CARDS_LIMIT]:
        if not p.wb_url:
            continue
        element = {
            "title": p.name[:80],
            "subtitle": f"{p.price:.0f} ₽",
            "buttons": [{"type": "web_url", "url": p.wb_url, "title": "Смотреть на WB"}],
        }
        if image_url := product_image_url(p):
            element["image_url"] = image_url
        elements.append(element)
    if not elements:
        return
    await _request("POST", f"{_account()}/messages", json={
        "recipient": {"id": igsid},
        "message": {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": elements}}},
    })


async def private_reply(comment_id: str, text: str) -> None:
    """Ответ автору комментария в Direct (разрешён один раз на комментарий, в течение 7 дней)."""
    await _request("POST", f"{_account()}/messages", json={
        "recipient": {"comment_id": comment_id},
        "message": {"text": text[:MESSAGE_LIMIT]},
    })


async def reply_to_comment(comment_id: str, text: str) -> None:
    """Публичный ответ под комментарием."""
    await _request("POST", f"{comment_id}/replies", params={"message": text})


async def publish_photo(image_url: str, caption: str) -> str:
    """Публикует пост с фото и возвращает его ID в Instagram."""
    container = await _request("POST", f"{_account()}/media", params={
        "image_url": image_url, "caption": caption[:CAPTION_LIMIT],
    })
    # Instagram скачивает и обрабатывает фото не мгновенно — ждём готовности контейнера
    for _ in range(10):
        status = await _request("GET", container["id"], params={"fields": "status_code"})
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") == "ERROR":
            raise InstagramError("Instagram не смог обработать фото")
        await asyncio.sleep(3)
    published = await _request("POST", f"{_account()}/media_publish", params={"creation_id": container["id"]})
    return published["id"]


async def refresh_token_if_needed() -> None:
    """Продлевает долгоживущий токен (живёт 60 дней), сохраняя новый в базу."""
    settings = get_settings()
    if not settings.instagram_enabled or settings.instagram_graph_host != INSTAGRAM_LOGIN_HOST:
        return
    async with SessionLocal() as session:
        stored = await session.get(AppSetting, TOKEN_KEY)
        if stored and utcnow() - stored.updated_at < TOKEN_REFRESH_EVERY:
            return
        token = stored.value if stored else settings.instagram_access_token
        async with aiohttp.ClientSession(timeout=TIMEOUT) as http:
            async with http.get(
                f"https://{INSTAGRAM_LOGIN_HOST}/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": token},
            ) as response:
                data = await response.json(content_type=None)
        if "access_token" not in data:
            logger.error("Instagram: не удалось продлить токен: %s", data.get("error", data))
            return
        if stored is None:
            session.add(AppSetting(key=TOKEN_KEY, value=data["access_token"]))
        else:
            stored.value = data["access_token"]
            stored.updated_at = utcnow()
        await session.commit()
        logger.info("Instagram: токен продлён")
