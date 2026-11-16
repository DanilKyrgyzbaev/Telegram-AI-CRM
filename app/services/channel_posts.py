"""Посты в Telegram-канал: AI пишет черновик, админ подтверждает, бот публикует."""

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.posts import write_post
from app.config import get_settings
from app.db import SessionLocal
from app.models import ChannelPost
from app.services.broadcasts import format_local, utcnow

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "generating": "AI пишет…",
    "draft": "черновик",
    "scheduled": "ждёт публикации",
    "publishing": "публикуется",
    "published": "опубликован",
    "failed": "ошибка",
}

# Ссылки на фоновые задачи, чтобы сборщик мусора не остановил их раньше времени
_tasks: set[asyncio.Task] = set()


def post_keyboard(post: ChannelPost) -> InlineKeyboardMarkup | None:
    """Кнопки под постом в канале: товар на WB и все товары магазина."""
    rows = []
    if post.product and post.product.wb_url:
        rows.append([InlineKeyboardButton(text="🛒 Смотреть на Wildberries", url=post.product.wb_url)])
    if shop_url := get_settings().shop_url:
        rows.append([InlineKeyboardButton(text="🛍 Все товары магазина", url=shop_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def admin_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Опубликовать", callback_data=f"post:publish:{post_id}")],
            [
                InlineKeyboardButton(text="🔄 Переписать", callback_data=f"post:rewrite:{post_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"post:delete:{post_id}"),
            ],
        ]
    )


def _preview(post: ChannelPost) -> LinkPreviewOptions:
    # Превью карточки WB над текстом — в канале будет видно фото товара
    if post.product and post.product.wb_url:
        return LinkPreviewOptions(url=post.product.wb_url, prefer_large_media=True, show_above_text=True)
    return LinkPreviewOptions(is_disabled=True)


async def _notify_admins(bot: Bot, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    for chat_id in get_settings().admin_ids:
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except TelegramAPIError:
            logger.exception("Не удалось отправить сообщение о посте админу %s", chat_id)


async def send_draft_to_admins(bot: Bot, post: ChannelPost) -> None:
    """Черновик в личку админам: так он будет выглядеть в канале, плюс кнопки «Опубликовать» и т. д."""
    for chat_id in get_settings().admin_ids:
        try:
            await bot.send_message(chat_id, f"📝 Черновик поста #{post.id} для канала:")
            await bot.send_message(
                chat_id, post.text, parse_mode="HTML",
                reply_markup=post_keyboard(post), link_preview_options=_preview(post),
            )
            await bot.send_message(chat_id, "Что делаем?", reply_markup=admin_keyboard(post.id))
        except TelegramAPIError:
            logger.exception("Не удалось отправить черновик поста %s админу %s", post.id, chat_id)


async def generate(bot: Bot, post_id: int, autopublish: bool = False) -> None:
    """AI пишет текст поста. Дальше — в очередь на публикацию или черновиком админам."""
    async with SessionLocal() as session:
        post = await session.get(ChannelPost, post_id)
        if post is None:
            return
        text = await write_post(session, post)
        if text is None:
            post.status = "draft"
            await session.commit()
            await _notify_admins(
                bot, f"⚠️ AI не смог написать пост #{post_id}. Напишите текст в админке или нажмите «Переписать».",
                InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Переписать", callback_data=f"post:rewrite:{post_id}")
                ]]),
            )
            return

        post.text = text
        if autopublish or post.scheduled_at is not None:
            post.status = "scheduled"
            post.scheduled_at = post.scheduled_at or utcnow()
        else:
            post.status = "draft"
        await session.commit()

    if post.status == "scheduled" and post.scheduled_at > utcnow():
        await _notify_admins(bot, f"🕒 Пост #{post_id} готов и выйдет в канале {format_local(post.scheduled_at)}.")
    elif post.status == "draft":
        await send_draft_to_admins(bot, post)


def start_generation(post_id: int, autopublish: bool = False) -> None:
    """Запускает AI в фоне — админка и бот не ждут, пока он пишет."""

    async def run() -> None:
        bot = Bot(get_settings().bot_token)
        try:
            await generate(bot, post_id, autopublish)
        except Exception:
            logger.exception("Channel post %s generation crashed", post_id)
        finally:
            await bot.session.close()

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def create_auto_post(*, product_id: int | None = None, discount_id: int | None = None) -> None:
    """Пост, который AI пишет сам: о новом товаре или промокоде."""
    async with SessionLocal() as session:
        post = ChannelPost(product_id=product_id, discount_id=discount_id, status="generating")
        session.add(post)
        await session.commit()
    start_generation(post.id, autopublish=get_settings().channel_autopublish)


async def claim(session: AsyncSession, post_id: int, statuses: tuple[str, ...]) -> ChannelPost | None:
    """Атомарно берёт пост в публикацию. None — его уже публикует кто-то другой или он не готов."""
    claimed = await session.scalar(
        update(ChannelPost)
        .where(ChannelPost.id == post_id, ChannelPost.status.in_(statuses), ChannelPost.text != "")
        .values(status="publishing")
        .returning(ChannelPost.id)
    )
    await session.commit()
    if claimed is None:
        return None
    post = await session.get(ChannelPost, post_id)
    await session.refresh(post)
    return post


async def publish(bot: Bot, session: AsyncSession, post: ChannelPost) -> bool:
    """Отправляет пост в канал. Итог (опубликован / ошибка) записывает в базу."""
    channel_id = get_settings().channel_id
    if not channel_id:
        post.status, post.error = "failed", "В .env не указан CHANNEL_ID"
        await session.commit()
        return False
    try:
        message = await bot.send_message(
            channel_id, post.text, parse_mode="HTML",
            reply_markup=post_keyboard(post), link_preview_options=_preview(post),
        )
    except TelegramAPIError as e:
        logger.exception("Channel post %s failed", post.id)
        # Частая причина — бот не админ канала или нет права публиковать сообщения
        post.status, post.error = "failed", str(e)
        await session.commit()
        return False
    post.status, post.error = "published", None
    post.message_id = message.message_id
    post.published_at = utcnow()
    await session.commit()
    return True


async def publish_and_report(bot: Bot, post_id: int, statuses: tuple[str, ...]) -> None:
    async with SessionLocal() as session:
        post = await claim(session, post_id, statuses)
        if post is None:
            return
        if await publish(bot, session, post):
            await _notify_admins(bot, f"✅ Пост #{post_id} опубликован в канале.")
        else:
            await _notify_admins(
                bot,
                f"⚠️ Пост #{post_id} не опубликован: {html.escape(post.error or '')}\n"
                "Проверьте, что бот — администратор канала с правом «Публикация сообщений».",
            )
