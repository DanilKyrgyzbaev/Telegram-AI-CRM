"""Webhook Instagram: Meta присылает сюда сообщения из Direct и комментарии к постам."""

import hashlib
import hmac
import json
import logging
from collections import OrderedDict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.ai import manager
from app.config import get_settings
from app.db import SessionLocal
from app.instagram import api
from app.models import ChannelPost
from app.services.clients import get_or_create_instagram_client
from app.services.limits import AI_LIMIT_TEXT, ai_limit_exceeded

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instagram", tags=["instagram"])

COMMENT_REPLY = "Ответили вам в директ 📩"

# Meta может прислать одно событие повторно — помним последние обработанные ID
_seen: OrderedDict[str, None] = OrderedDict()
SEEN_LIMIT = 5000


def _first_time(event_id: str) -> bool:
    if event_id in _seen:
        return False
    _seen[event_id] = None
    if len(_seen) > SEEN_LIMIT:
        _seen.popitem(last=False)
    return True


def _valid_signature(body: bytes, signature: str | None) -> bool:
    secret = get_settings().instagram_app_secret
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


@router.get("/webhook", response_class=PlainTextResponse)
async def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> str:
    """Проверка при подключении webhook в кабинете Meta."""
    expected = get_settings().instagram_verify_token
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        return challenge
    raise HTTPException(status_code=403)


@router.post("/webhook")
async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
    body = await request.body()
    if not _valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403)
    # Meta ждёт ответ быстро, иначе повторит событие — AI отвечает уже в фоне
    background.add_task(_dispatch, json.loads(body))
    return {"status": "ok"}


async def _dispatch(payload: dict) -> None:
    for entry in payload.get("entry", []):
        # Свои же сообщения и комментарии (в том числе наш ответ «Ответили в директ») не обрабатываем
        own_ids = {get_settings().instagram_account_id, entry.get("id")}
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            sender = (event.get("sender") or {}).get("id")
            # is_echo — наши собственные исходящие сообщения
            if message.get("is_echo") or not message.get("text") or sender in own_ids:
                continue
            if _first_time(message.get("mid", "")):
                await _safe(_on_message(sender, message["text"]))
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            author = (value.get("from") or {}).get("id")
            if change.get("field") != "comments" or not value.get("text") or author in own_ids:
                continue
            if _first_time(value.get("id", "")):
                await _safe(_on_comment(
                    value["id"], author, value.get("from", {}).get("username"), value["text"],
                    (value.get("media") or {}).get("id"),
                ))


async def _safe(coro) -> None:
    try:
        await coro
    except Exception:
        logger.exception("Instagram webhook handling failed")


async def _client(session, igsid: str, username: str | None = None):
    profile = await api.user_profile(igsid) if username is None else {}
    username = username or profile.get("username")
    full_name = profile.get("name") or username or "Instagram"
    return await get_or_create_instagram_client(session, igsid, full_name, username)


async def _on_message(igsid: str, text: str) -> None:
    async with SessionLocal() as session:
        crm_client = await _client(session, igsid)
        # Каждый ответ AI платный — те же лимиты, что и в Telegram
        if limit := await ai_limit_exceeded(session, crm_client):
            await api.send_text(igsid, AI_LIMIT_TEXT[limit])
            return
        answer = await manager.reply(session, crm_client, text)
    await api.send_text(igsid, answer.text)
    if answer.products:
        await api.send_products(igsid, answer.products)


async def _on_comment(comment_id: str, igsid: str, username: str | None, text: str, media_id: str | None) -> None:
    async with SessionLocal() as session:
        crm_client = await _client(session, igsid, username)
        if await ai_limit_exceeded(session, crm_client):
            return
        # Пост опубликовала наша система — AI знает, о каком товаре спрашивают («сколько стоит?»)
        post = media_id and await session.scalar(
            select(ChannelPost).where(ChannelPost.instagram_media_id == media_id)
        )
        product = post.product if post else None
        answer = await manager.reply_to_comment(session, crm_client, text, product)
    # Сначала личное сообщение, потом публичная отметка — другие видят, что магазин отвечает.
    # Карточки товаров не шлём: до ответа клиента Instagram разрешает только одно сообщение
    await api.private_reply(comment_id, answer.text)
    await api.reply_to_comment(comment_id, COMMENT_REPLY)
