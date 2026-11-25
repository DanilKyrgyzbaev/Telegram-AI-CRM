"""Подбор размера кнопками: рост → вес → посадка, затем AI советует размер для товара из контекста."""

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import manager
from app.bot.keyboards import FITS, HEIGHTS, WEIGHTS, fit_keyboard, products_keyboard, weight_keyboard
from app.models import Message as ChatMessage
from app.services.clients import get_or_create_client
from app.services.limits import AI_LIMIT_TEXT, ai_limit_exceeded

router = Router()


async def _remember(message: Message, session: AsyncSession, text: str):
    """Ответ-кнопку сохраняем в истории диалога — AI увидит его, когда будет советовать размер."""
    user = message.from_user
    crm_client = await get_or_create_client(
        session, telegram_id=user.id, full_name=user.full_name, username=user.username
    )
    session.add(ChatMessage(client_id=crm_client.id, role="user", text=text))
    await session.commit()
    return crm_client


@router.message(F.text.in_(HEIGHTS))
async def height(message: Message, session: AsyncSession) -> None:
    await _remember(message, session, f"Мой рост: {message.text}")
    await message.answer("А вес?", reply_markup=weight_keyboard())


@router.message(F.text.in_(WEIGHTS))
async def weight(message: Message, session: AsyncSession) -> None:
    await _remember(message, session, f"Мой вес: {message.text}")
    await message.answer("Как любите носить?", reply_markup=fit_keyboard())


@router.message(F.text.in_(FITS))
async def fit(message: Message, session: AsyncSession) -> None:
    user = message.from_user
    crm_client = await get_or_create_client(
        session, telegram_id=user.id, full_name=user.full_name, username=user.username
    )
    if limit := await ai_limit_exceeded(session, crm_client):
        await message.answer(AI_LIMIT_TEXT[limit], reply_markup=ReplyKeyboardRemove())
        return
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    answer = await manager.reply(session, crm_client, f"Посадка: {message.text.lower()}. Какой размер мне взять?")
    # Кнопки-ответы убираем; кнопки на товары WB — отдельным сообщением (у одного сообщения одна клавиатура)
    await message.answer(answer.text, reply_markup=ReplyKeyboardRemove())
    if keyboard := products_keyboard(answer.products):
        await message.answer("Посмотреть на Wildberries 👇", reply_markup=keyboard)
