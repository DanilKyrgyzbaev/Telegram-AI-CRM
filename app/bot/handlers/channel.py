from aiogram import F, Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.types import CallbackQuery, ChatMemberUpdated
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client
from app.services.clients import get_or_create_client
from app.services.subscription import is_our_channel, refresh_subscription

router = Router()


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery, session: AsyncSession) -> None:
    user = callback.from_user
    client = await get_or_create_client(
        session, telegram_id=user.id, full_name=user.full_name, username=user.username
    )
    subscribed = await refresh_subscription(callback.bot, session, client)

    if subscribed is None:
        await callback.answer("Не удалось проверить подписку, попробуйте позже.", show_alert=True)
    elif subscribed:
        await callback.answer()
        await callback.message.edit_text("Спасибо за подписку! 🎉 Напишите, что вас интересует.")
    else:
        await callback.answer("Подписка не найдена. Подпишитесь на канал и нажмите ещё раз.", show_alert=True)


# Telegram присылает эти события, только если бот — админ канала.
# Так CRM узнаёт о подписке и отписке сразу, без нажатия кнопки.
@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_subscribe(event: ChatMemberUpdated, session: AsyncSession) -> None:
    await _set_subscribed(event, session, True)


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_unsubscribe(event: ChatMemberUpdated, session: AsyncSession) -> None:
    await _set_subscribed(event, session, False)


async def _set_subscribed(event: ChatMemberUpdated, session: AsyncSession, subscribed: bool) -> None:
    if not is_our_channel(event.chat):
        return
    # Обновляем только тех, кто уже писал боту: остальных боту всё равно нельзя написать первым
    client = await session.scalar(select(Client).where(Client.telegram_id == event.new_chat_member.user.id))
    if client is not None:
        client.subscribed = subscribed
        await session.commit()
