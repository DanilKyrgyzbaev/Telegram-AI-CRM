from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import manager
from app.bot.keyboards import products_keyboard, subscribe_keyboard
from app.models import Product, Purchase
from app.services.clients import get_or_create_client
from app.services.promo import current_promo, format_expires
from app.services.qr import parse_start_param

router = Router()


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, session: AsyncSession) -> None:
    user = message.from_user
    # t.me/bot?start=p15 — QR с упаковки товара №15; любой другой параметр — метка кампании
    product_id = parse_start_param(command.args)
    crm_client = await get_or_create_client(
        session,
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
        source="qr" if product_id else command.args,
    )

    product = await session.get(Product, product_id) if product_id else None
    if product is None:
        await message.answer(
            f"Здравствуйте, {user.first_name}! 👋\n"
            "Я помогу подобрать товар и отвечу на любые вопросы. Просто напишите, что вас интересует.",
            reply_markup=subscribe_keyboard(),
        )
        return

    session.add(Purchase(client_id=crm_client.id, product_id=product.id))
    await session.commit()
    promo = await current_promo(session)

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    answer = await manager.greet_purchase(session, crm_client, product, promo)
    if promo is None:
        await message.answer(answer.text, reply_markup=products_keyboard(answer.products, with_subscribe=True))
        return

    await message.answer(answer.text, reply_markup=products_keyboard(answer.products))
    # Код отправляет система, а не AI, — так в нём точно не будет ошибки
    await message.answer(
        f"🎁 Промокод на следующий заказ на Wildberries: <code>{promo.code}</code>\n"
        f"Скидка {promo.percent}% — действует до {format_expires(promo)}.\n"
        "Нажмите на код, чтобы скопировать, и введите его при оформлении заказа.",
        parse_mode="HTML",
        reply_markup=subscribe_keyboard(),
    )
