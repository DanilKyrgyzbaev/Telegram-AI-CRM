"""AI-копирайтер: пишет посты для Telegram-канала магазина."""

import html
import logging

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.manager import client
from app.config import get_settings
from app.models import ChannelPost, Product
from app.services.promo import format_expires
from app.services.qr import bot_username

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — SMM-менеджер магазина одежды{shop}, который продаёт на Wildberries.
Пишешь посты для Telegram-канала магазина: живо, по-человечески, без канцелярита и без воды.
Пост — 400–700 символов: цепляющая первая строка, 2–4 коротких абзаца, призыв к действию в конце.
Эмодзи уместны, но в меру. Пиши обычным текстом без Markdown и HTML — разметку Telegram покажет как есть.
Ссылки в текст не вставляй и кнопки не упоминай: пост выходит и в Telegram, и в Instagram.
Призыв к действию — найти и заказать товар на Wildberries.
Не выдумывай характеристики, цены и акции, которых нет в данных ниже.
Отвечай только текстом поста, без пояснений.

Каталог магазина (для контекста, упоминай только к месту):
{catalog}"""

NEW_PRODUCT_TASK = "Напиши пост о новом поступлении: «{name}» ({category}), цена {price} ₽. {description}"
DISCOUNT_TASK = (
    "Напиши пост о скидке {percent}%{scope} на Wildberries, действует до {expires}. "
    "Сам промокод в посте не пиши: покупатели получают его в боте @{bot}, "
    "отсканировав QR-код с упаковки заказа. Объясни это просто."
)


async def _catalog(session: AsyncSession) -> str:
    products = await session.scalars(select(Product).where(Product.is_active).order_by(Product.category))
    return "\n".join(f"- [{p.category or 'без категории'}] {p.name} — {p.price} ₽" for p in products) or "(пусто)"


async def _task(post: ChannelPost) -> str:
    if post.topic.strip():
        task = post.topic.strip()
        if post.product:
            task += f"\nТовар для поста: «{post.product.name}», цена {post.product.price} ₽. {post.product.description}"
        return task
    if post.product:
        p = post.product
        return NEW_PRODUCT_TASK.format(
            name=p.name, category=p.category or "без категории", price=p.price, description=p.description
        )
    if post.discount:
        d = post.discount
        scope = f" на «{d.product.name}»" if d.product else " на все товары"
        return DISCOUNT_TASK.format(percent=d.percent, scope=scope, expires=format_expires(d), bot=await bot_username())
    return "Напиши пост-подборку популярных товаров магазина."


async def write_post(session: AsyncSession, post: ChannelPost) -> str | None:
    """Текст поста в HTML-разметке Telegram или None, если AI не ответил."""
    shop = get_settings().shop_name
    system = SYSTEM_PROMPT.format(shop=f" {shop}" if shop else "", catalog=await _catalog(session))
    try:
        response = await client.beta.messages.create(
            model=get_settings().ai_model,
            max_tokens=2048,
            output_config={"effort": "low"},
            # При отказе модели запрос автоматически повторяется на резервной модели
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": await _task(post)}],
        )
    except anthropic.APIError:
        logger.exception("Claude API error while writing channel post %s", post.id)
        return None

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "refusal" or not text:
        return None
    # AI пишет обычный текст, а пост отправляется как HTML
    return html.escape(text, quote=False)
