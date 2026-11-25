import json
import logging
from dataclasses import dataclass, field

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Client, Discount, Message, Product, Purchase
from app.services.promo import current_promo, format_expires

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20

SYSTEM_PROMPT = """Ты — вежливый менеджер по продажам магазина, который продаёт товары на Wildberries.
Помогай клиенту выбрать товар, отвечай на вопросы, рекомендуй подходящие позиции.
Опирайся только на каталог ниже; если товара нет — честно скажи об этом.
Не предлагай повторно то, что клиент уже купил, — лучше то, что с этим сочетается.
Отвечай кратко, на языке клиента.
Пиши обычным текстом без Markdown (без звёздочек и решёток) — Telegram покажет разметку как есть. Эмодзи можно.
Ссылки в текст не вставляй: в product_ids перечисли номера (#) товаров, которые ты упомянул в ответе, —
под сообщением появятся кнопки, ведущие на эти товары на Wildberries.
Сообщения в квадратных скобках — служебные события от системы, а не слова клиента.

Каталог:
{catalog}

Покупки клиента:
{purchases}

Действующий промокод на Wildberries:
{promo}"""

# Ответ AI: текст для клиента + товары, на которые нужны кнопки
REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "product_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["text", "product_ids"],
    "additionalProperties": False,
}

PURCHASE_EVENT = (
    "[Клиент купил «{name}» и отсканировал QR-код с упаковки. "
    "Поблагодари за покупку и предложи 2–3 товара из каталога, "
    "которые подходят к ней или похожи на неё.{promo_note}]"
)
PROMO_NOTE = (
    " Сразу после твоего ответа система отдельным сообщением пришлёт клиенту промокод "
    "на скидку {percent}% для следующего заказа на Wildberries — коротко упомяни это, сам код не пиши."
)

COMMENT_EVENT = (
    "[Клиент оставил комментарий под постом в Instagram{about}: «{text}». "
    "Ты пишешь ему в личные сообщения в ответ на этот комментарий: поблагодари, ответь на вопрос, "
    "если он есть, и предложи помочь с выбором. Коротко.]"
)

FALLBACK = "Извините, сейчас не получается ответить. Напишите, пожалуйста, чуть позже."

# Ключ читается из ANTHROPIC_API_KEY
client = anthropic.AsyncAnthropic()


@dataclass
class AIReply:
    text: str
    # Товары, которые AI упомянул: под сообщением будут кнопки на Wildberries
    products: list[Product] = field(default_factory=list)


async def _catalog(session: AsyncSession) -> str:
    products = await session.scalars(select(Product).where(Product.is_active).order_by(Product.category))
    lines = [
        f"- #{p.id} [{p.category or 'без категории'}] {p.name} — {p.price} ₽. {p.description}"
        for p in products
    ]
    return "\n".join(lines) or "(пусто)"


async def _purchases(session: AsyncSession, crm_client: Client) -> str:
    names = await session.scalars(
        select(Product.name).join(Purchase).where(Purchase.client_id == crm_client.id).distinct()
    )
    return ", ".join(names) or "пока нет"


async def _promo(session: AsyncSession) -> str:
    promo = await current_promo(session)
    if promo is None:
        return "нет"
    scope = f" на «{promo.product.name}»" if promo.product else ""
    return f"{promo.code} — скидка {promo.percent}%{scope}, действует до {format_expires(promo)}"


async def reply(session: AsyncSession, crm_client: Client, text: str) -> AIReply:
    """Ответ AI-менеджера на сообщение клиента."""
    session.add(Message(client_id=crm_client.id, role="user", text=text))
    return await _generate(session, crm_client, FALLBACK)


async def greet_purchase(
    session: AsyncSession, crm_client: Client, product: Product, promo: Discount | None = None
) -> AIReply:
    """Первое сообщение после сканирования QR: благодарность и рекомендации."""
    promo_note = PROMO_NOTE.format(percent=promo.percent) if promo else ""
    event = PURCHASE_EVENT.format(name=product.name, promo_note=promo_note)
    session.add(Message(client_id=crm_client.id, role="event", text=event))
    fallback = f"Спасибо за покупку «{product.name}»! 🙌 Если захотите подобрать что-то к ней — просто напишите."
    return await _generate(session, crm_client, fallback)


async def note_product_interest(session: AsyncSession, crm_client: Client, product: Product) -> None:
    """Клиент нажал «Спросить AI» на товаре в каталоге: запоминаем, о чём будет следующий вопрос."""
    session.add(Message(
        client_id=crm_client.id, role="event",
        text=f"[Клиент открыл в каталоге товар #{product.id} «{product.name}» и хочет задать о нём вопрос]",
    ))
    await session.commit()


async def reply_to_comment(
    session: AsyncSession, crm_client: Client, comment: str, product: Product | None = None
) -> AIReply:
    """Сообщение в Direct автору комментария в Instagram. product — товар из поста, если он известен."""
    about = f" о товаре #{product.id} «{product.name}»" if product else ""
    event = COMMENT_EVENT.format(about=about, text=comment)
    session.add(Message(client_id=crm_client.id, role="event", text=event))
    fallback = "Спасибо за комментарий! 🙌 Если хотите, помогу подобрать размер или модель — просто напишите."
    return await _generate(session, crm_client, fallback)


async def _generate(session: AsyncSession, crm_client: Client, fallback: str) -> AIReply:
    await session.flush()
    rows = await session.scalars(
        select(Message)
        .where(Message.client_id == crm_client.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
    )
    # События передаём модели как реплики пользователя — они помечены квадратными скобками
    history = [
        {"role": "assistant" if m.role == "assistant" else "user", "content": m.text}
        for m in reversed(list(rows))
    ]
    # История должна начинаться с реплики пользователя
    while history and history[0]["role"] != "user":
        history.pop(0)

    system = SYSTEM_PROMPT.format(
        catalog=await _catalog(session),
        purchases=await _purchases(session, crm_client),
        promo=await _promo(session),
    )
    try:
        response = await client.beta.messages.create(
            model=get_settings().ai_model,
            max_tokens=2048,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": REPLY_SCHEMA}},
            # При отказе модели запрос автоматически повторяется на резервной модели
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=history,
        )
    except anthropic.APIError:
        logger.exception("Claude API error for client %s", crm_client.id)
        # Сообщение клиента сохраняем, чтобы оно было видно в CRM
        await session.commit()
        return AIReply(fallback)

    raw = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(raw)
        answer, product_ids = data["text"].strip(), data["product_ids"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        # Например, отказ модели: JSON по схеме не гарантирован
        answer, product_ids = "", []
    if response.stop_reason == "refusal" or not answer:
        answer, product_ids = fallback, []

    products = []
    if product_ids:
        products = list(
            await session.scalars(select(Product).where(Product.id.in_(product_ids), Product.is_active))
        )

    session.add(Message(client_id=crm_client.id, role="assistant", text=answer))
    await session.commit()
    return AIReply(answer, products)
