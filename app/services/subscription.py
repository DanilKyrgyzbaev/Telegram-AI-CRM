import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Chat
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Client

logger = logging.getLogger(__name__)

MEMBER_STATUSES = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}


def is_our_channel(chat: Chat) -> bool:
    channel_id = get_settings().channel_id
    if channel_id.startswith("@"):
        return chat.username is not None and chat.username.lower() == channel_id[1:].lower()
    return str(chat.id) == channel_id


async def refresh_subscription(bot: Bot, session: AsyncSession, client: Client) -> bool | None:
    """Спрашивает у Telegram, подписан ли клиент, и сохраняет ответ в CRM.

    None — проверить не удалось (канал не настроен или бот не админ канала).
    """
    channel_id = get_settings().channel_id
    if not channel_id:
        return None
    try:
        member = await bot.get_chat_member(channel_id, client.telegram_id)
    except TelegramAPIError:
        logger.exception("Не удалось проверить подписку %s на %s", client.telegram_id, channel_id)
        return None

    subscribed = member.status in MEMBER_STATUSES or (
        member.status == ChatMemberStatus.RESTRICTED and member.is_member
    )
    if client.subscribed != subscribed:
        client.subscribed = subscribed
        await session.commit()
    return subscribed
