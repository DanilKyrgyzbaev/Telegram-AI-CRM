from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import manager
from app.bot.keyboards import products_keyboard, subscribe_keyboard
from app.models import Discount, Product, Purchase
from app.services.clients import get_or_create_client
from app.services.limits import is_repeat_scan, qr_limit_exceeded
from app.services.promo import current_promo, format_expires
from app.bot.keyboards import catalog_menu_button
from app.services.qr import parse_product_question, parse_start_param, source_for

router = Router()


def _promo_text(promo: Discount) -> str:
    return (
        f"🎁 Промокод на следующий заказ на Wildberries: <code>{promo.code}</code>\n"
        f"Скидка {promo.percent}% — действует до {format_expires(promo)}.\n"
        "Нажмите на код, чтобы скопировать, и введите его при оформлении заказа."
    )


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, session: AsyncSession) -> None:
    user = message.from_user
    # t.me/bot?start=q<код> — QR с упаковки товара; любой другой параметр — метка кампании
    qr_token = parse_start_param(command.args)
    crm_client = await get_or_create_client(
        session,
        telegram_id=user.id,
        full_name=user.full_name,
        username=user.username,
        source=source_for(command.args),
    )
    # Кнопка «Каталог» у поля ввода: ставим каждому чату — значение «для всех» Telegram применяет не всегда
    if menu_button := catalog_menu_button():
        await message.bot.set_chat_menu_button(chat_id=message.chat.id, menu_button=menu_button)

    # Пришли спросить о товаре (из каталога или кнопкой «Спросить про размер» на сайте):
    # следующий вопрос AI поймёт в контексте этого товара
    if (question := parse_product_question(command.args)) and (asked := await session.get(Product, question[1])):
        about_size = question[0] == "size"
        await manager.note_product_interest(session, crm_client, asked, about_size)
        await message.answer(manager.product_question_text(asked, about_size))
        return

    product = None
    if qr_token:
        product = await session.scalar(select(Product).where(Product.qr_token == qr_token))
    # Слишком много разных QR за сутки — похоже на накрутку: здороваемся, но покупку не засчитываем
    if product is None or await qr_limit_exceeded(session, crm_client):
        await message.answer(
            f"Здравствуйте, {user.first_name}! 👋\n"
            "Я помогу подобрать товар и отвечу на любые вопросы. Просто напишите, что вас интересует.",
            reply_markup=subscribe_keyboard(),
        )
        return

    promo = await current_promo(session)

    # Тот же QR отсканирован повторно: покупку не дублируем и AI не вызываем, промокод напоминаем
    if await is_repeat_scan(session, crm_client, product.id):
        text = (
            f"Рады видеть вас снова! 🙌 Покупку «{product.name}» мы уже отметили.\n"
            "Если хотите подобрать что-то к ней — просто напишите."
        )
        if promo is None:
            await message.answer(text, reply_markup=subscribe_keyboard())
        else:
            await message.answer(text)
            await message.answer(_promo_text(promo), parse_mode="HTML", reply_markup=subscribe_keyboard())
        return

    session.add(Purchase(client_id=crm_client.id, product_id=product.id))
    await session.commit()

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    answer = await manager.greet_purchase(session, crm_client, product, promo)
    if promo is None:
        await message.answer(answer.text, reply_markup=products_keyboard(answer.products, with_subscribe=True))
        return

    await message.answer(answer.text, reply_markup=products_keyboard(answer.products))
    # Код отправляет система, а не AI, — так в нём точно не будет ошибки
    await message.answer(_promo_text(promo), parse_mode="HTML", reply_markup=subscribe_keyboard())
