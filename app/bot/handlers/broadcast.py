import asyncio
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Broadcast
from app.services.broadcasts import format_local, local_tz, recipients_query, run_and_report, utcnow

router = Router()
# Все хендлеры этого роутера — только для админов
is_admin = F.from_user.id.in_(get_settings().admin_ids)
router.message.filter(is_admin)
router.callback_query.filter(is_admin)

# Ссылки на фоновые задачи, чтобы сборщик мусора не остановил их раньше времени
_tasks: set[asyncio.Task] = set()

CONFIRM_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить сейчас", callback_data="broadcast:confirm")],
        [InlineKeyboardButton(text="🕒 Запланировать", callback_data="broadcast:schedule")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
    ]
)


class BroadcastForm(StatesGroup):
    text = State()
    confirm = State()
    schedule = State()


def parse_local_datetime(text: str) -> datetime:
    """«25.12 18:00» или «25.12.2026 18:00» в часовом поясе админа → UTC для базы."""
    date_part, _, time_part = text.strip().partition(" ")
    if date_part.count(".") == 1:
        date_part += f".{datetime.now(local_tz()).year}"
    local = datetime.strptime(f"{date_part} {time_part.strip()}", "%d.%m.%Y %H:%M")
    return local.replace(tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)


@router.message(Command("broadcast"))
async def broadcast_start(message: Message, command: CommandObject, state: FSMContext) -> None:
    # /broadcast <метка> — рассылка только клиентам одной рекламной кампании
    await state.set_state(BroadcastForm.text)
    await state.update_data(source=command.args)
    audience = f"клиентам из кампании «{command.args}»" if command.args else "всем клиентам"
    await message.answer(
        f"Рассылка {audience}.\n"
        "Пришлите текст сообщения (можно HTML: <b>жирный</b>, <i>курсив</i>, ссылки).\n"
        "/cancel — отменить.",
        parse_mode=None,
    )


@router.message(Command("cancel"))
async def broadcast_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Рассылка отменена.")


@router.message(BroadcastForm.text, F.text)
async def broadcast_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    recipients = await session.scalar(
        select(func.count()).select_from(recipients_query(data["source"]).subquery())
    )

    try:
        # Превью: админ видит сообщение ровно так, как его увидят клиенты
        await message.answer(message.html_text, parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.answer(f"Ошибка в HTML-разметке: {e.message}\nПришлите текст ещё раз.")
        return

    await state.update_data(text=message.html_text)
    await state.set_state(BroadcastForm.confirm)
    await message.answer(f"Отправить это сообщение {recipients} клиентам?", reply_markup=CONFIRM_KEYBOARD)


@router.callback_query(BroadcastForm.confirm, F.data == "broadcast:cancel")
async def broadcast_cancel_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.")


@router.callback_query(BroadcastForm.confirm, F.data == "broadcast:confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()

    broadcast = Broadcast(text=data["text"], source=data["source"])
    session.add(broadcast)
    await session.commit()

    await callback.message.edit_text(f"🚀 Рассылка #{broadcast.id} запущена. Сообщу, когда закончится.")
    task = asyncio.create_task(run_and_report(callback.bot, [callback.from_user.id], broadcast.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@router.callback_query(BroadcastForm.confirm, F.data == "broadcast:schedule")
async def broadcast_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastForm.schedule)
    await callback.message.edit_text(
        "Когда отправить? Напишите дату и время, например <code>25.12 18:00</code>.\n"
        f"Часовой пояс: {get_settings().timezone}. /cancel — отменить.",
        parse_mode="HTML",
    )


@router.message(BroadcastForm.schedule, F.text)
async def broadcast_schedule_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        scheduled_at = parse_local_datetime(message.text)
    except ValueError:
        await message.answer("Не понял дату. Формат: ДД.ММ ЧЧ:ММ, например 25.12 18:00")
        return
    if scheduled_at <= utcnow():
        await message.answer("Это время уже прошло. Укажите время в будущем.")
        return

    data = await state.get_data()
    await state.clear()
    broadcast = Broadcast(text=data["text"], source=data["source"], status="scheduled", scheduled_at=scheduled_at)
    session.add(broadcast)
    await session.commit()

    await message.answer(
        f"🕒 Рассылка #{broadcast.id} запланирована на {format_local(scheduled_at)}.\n"
        "Список и отмена — /scheduled"
    )


async def _scheduled_list(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    broadcasts = (
        await session.scalars(
            select(Broadcast).where(Broadcast.status == "scheduled").order_by(Broadcast.scheduled_at)
        )
    ).all()
    if not broadcasts:
        return "Запланированных рассылок нет.", None

    lines = ["Запланированные рассылки:"]
    buttons = []
    for b in broadcasts:
        preview = b.text if len(b.text) <= 50 else b.text[:50] + "…"
        lines.append(f"\n#{b.id} — {format_local(b.scheduled_at)}\n{preview}")
        buttons.append([InlineKeyboardButton(text=f"❌ Отменить #{b.id}", callback_data=f"broadcast:delete:{b.id}")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("scheduled"))
async def scheduled_list(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _scheduled_list(session)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("broadcast:delete:"))
async def scheduled_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    broadcast_id = int(callback.data.rsplit(":", 1)[1])
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None or broadcast.status != "scheduled":
        await callback.answer("Эта рассылка уже отправлена или отменена.", show_alert=True)
    else:
        await session.delete(broadcast)
        await session.commit()
        await callback.answer(f"Рассылка #{broadcast_id} отменена.")

    text, keyboard = await _scheduled_list(session)
    await callback.message.edit_text(text, reply_markup=keyboard)
