from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import manager
from app.bot.keyboards import products_keyboard, subscribe_keyboard
from app.config import get_settings
from app.services.clients import get_or_create_client
from app.services.limits import AI_LIMIT_TEXT, ai_limit_exceeded
from app.services.subscription import refresh_subscription

router = Router()


@router.message(F.text)
async def chat(message: Message, session: AsyncSession) -> None:
    user = message.from_user
    crm_client = await get_or_create_client(
        session, telegram_id=user.id, full_name=user.full_name, username=user.username
    )

    # Подписчиков не перепроверяем на каждое сообщение: об отписке сообщит событие chat_member.
    # None (проверка не удалась) не блокирует клиента — лучше ответить, чем потерять продажу
    if get_settings().require_subscription and not crm_client.subscribed:
        if await refresh_subscription(message.bot, session, crm_client) is False:
            await message.answer(
                "Чтобы получить консультацию, подпишитесь на наш канал 👇",
                reply_markup=subscribe_keyboard(),
            )
            return

    # Каждый ответ AI платный — не даём одному человеку слать сообщения без счёта
    if limit := await ai_limit_exceeded(session, crm_client):
        await message.answer(AI_LIMIT_TEXT[limit])
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    answer = await manager.reply(session, crm_client, message.text)
    await message.answer(answer.text, reply_markup=products_keyboard(answer.products))
