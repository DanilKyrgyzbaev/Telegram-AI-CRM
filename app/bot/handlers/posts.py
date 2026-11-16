from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ChannelPost
from app.services.channel_posts import publish_and_report, start_generation

router = Router()
# Все хендлеры этого роутера — только для админов
is_admin = F.from_user.id.in_(get_settings().admin_ids)
router.message.filter(is_admin)
router.callback_query.filter(is_admin)


@router.message(Command("post"))
async def post_command(message: Message, command: CommandObject, session: AsyncSession) -> None:
    # /post <задание> — AI пишет пост в канал, черновик придёт сюда с кнопкой «Опубликовать»
    if not command.args:
        await message.answer(
            "Напишите задание для поста после команды, например:\n"
            "/post скидки чёрной пятницы на тёплые брюки\n"
            "/post подборка худи на зиму"
        )
        return
    post = ChannelPost(topic=command.args, status="generating")
    session.add(post)
    await session.commit()
    await message.answer(f"✍️ AI пишет пост #{post.id}, пришлю черновик через несколько секунд.")
    start_generation(post.id)


@router.callback_query(F.data.startswith("post:publish:"))
async def post_publish(callback: CallbackQuery) -> None:
    post_id = int(callback.data.rsplit(":", 1)[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Публикую…")
    await publish_and_report(callback.bot, post_id, ("draft", "failed"))


@router.callback_query(F.data.startswith("post:rewrite:"))
async def post_rewrite(callback: CallbackQuery, session: AsyncSession) -> None:
    post = await session.get(ChannelPost, int(callback.data.rsplit(":", 1)[1]))
    if post is None or post.status not in ("draft", "failed"):
        await callback.answer("Этот пост уже нельзя переписать.", show_alert=True)
        return
    post.status = "generating"
    await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Пишу новый вариант…")
    start_generation(post.id)


@router.callback_query(F.data.startswith("post:delete:"))
async def post_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    post = await session.get(ChannelPost, int(callback.data.rsplit(":", 1)[1]))
    if post is not None and post.status in ("draft", "failed"):
        await session.delete(post)
        await session.commit()
        await callback.message.edit_text("🗑 Черновик удалён.")
    else:
        await callback.answer("Этот пост уже нельзя удалить.", show_alert=True)
