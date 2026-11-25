"""AI-копирайтер: пишет посты для Telegram-канала и Instagram, тексты для сторис."""

import html
import logging

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.manager import client
from app.config import get_settings
from app.models import ChannelPost, Product
from app.services.broadcasts import utcnow
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

# Ежедневный контент-план: рубрика по дню недели (0 — понедельник). В каждой рубрике есть товар —
# у поста будет фото, поэтому он выйдет и в Instagram. Отзывов нет: выдумывать их нельзя
RUBRICS = {
    "spotlight": ("Модель недели", "Расскажи о модели «{name}» ({category}, {price} ₽): для кого она, "
                  "в чём её плюсы, с чем носить. {description}"),
    "style_tip": ("Совет по стилю", "Дай один практичный совет по стилю (как сочетать, как выглядеть "
                  "стройнее, как собрать образ за минуту) и покажи его на примере «{name}» ({price} ₽). {description}"),
    "outfit": ("Образ дня", "Собери образ дня вокруг «{name}» ({price} ₽): с чем из нашего каталога его "
               "носить и куда в нём пойти. {description}"),
    "season": ("К сезону", "Напиши пост к текущему сезону и погоде (сейчас {month}): почему «{name}» "
               "({price} ₽) пригодится именно сейчас. {description}"),
    "promo": ("Акция", ""),
    "care": ("Выбор и уход", "Дай полезные советы: как выбрать размер и посадку и как ухаживать за вещью, "
             "на примере «{name}» ({category}). Таблицы размеров не придумывай — советуй сверяться "
             "с таблицей в карточке на Wildberries. {description}"),
    "weekend": ("Выходные", "Напиши уютный пост к выходным: настроение, отдых, прогулка — и «{name}» "
                "({price} ₽) как вещь, в которой хорошо провести выходные. {description}"),
}
RUBRIC_BY_WEEKDAY = ("spotlight", "style_tip", "outfit", "season", "promo", "care", "weekend")
MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
          "сентябрь", "октябрь", "ноябрь", "декабрь")

STORY_PROMPT = """Ты — SMM-менеджер магазина одежды{shop}. Придумай текст для сторис в Instagram:
он будет крупно напечатан на картинке поверх фото товара.
Ответь ровно двумя строками без кавычек, эмодзи, хэштегов и пояснений:
1-я строка — цепляющий заголовок до 28 символов;
2-я строка — пояснение до 60 символов, почему стоит посмотреть товар.
Цену не пиши: её добавят отдельно. Не выдумывай характеристик, которых нет в описании."""
STORY_TITLE_LIMIT = 28
STORY_LINE_LIMIT = 60


async def _catalog(session: AsyncSession) -> str:
    products = await session.scalars(select(Product).where(Product.is_active).order_by(Product.category))
    return "\n".join(f"- [{p.category or 'без категории'}] {p.name} — {p.price} ₽" for p in products) or "(пусто)"


async def _discount_task(post: ChannelPost) -> str:
    d = post.discount
    scope = f" на «{d.product.name}»" if d.product else " на все товары"
    return DISCOUNT_TASK.format(percent=d.percent, scope=scope, expires=format_expires(d), bot=await bot_username())


async def _task(post: ChannelPost) -> str:
    if post.rubric == "promo" and post.discount:
        task = await _discount_task(post)
        # Фото товара в посте нужно для Instagram — покажем скидку на его примере
        if post.product:
            task += f" Покажи на примере «{post.product.name}» ({post.product.price} ₽)."
        return task
    if post.rubric in RUBRICS and post.product and RUBRICS[post.rubric][1]:
        p = post.product
        return RUBRICS[post.rubric][1].format(
            name=p.name, category=p.category or "без категории", price=p.price, description=p.description,
            month=MONTHS[utcnow().month - 1],
        )
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
        return await _discount_task(post)
    return "Напиши пост-подборку популярных товаров магазина."


async def _ask(post: ChannelPost, system: str, task: str) -> str | None:
    try:
        response = await client.beta.messages.create(
            model=get_settings().ai_model,
            max_tokens=2048,
            output_config={"effort": "low"},
            # При отказе модели запрос автоматически повторяется на резервной модели
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": task}],
        )
    except anthropic.APIError:
        logger.exception("Claude API error while writing channel post %s", post.id)
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "refusal" or not text:
        return None
    return text


def _shop() -> str:
    shop = get_settings().shop_name
    return f" {shop}" if shop else ""


async def write_post(session: AsyncSession, post: ChannelPost) -> str | None:
    """Текст поста в HTML-разметке Telegram или None, если AI не ответил."""
    if post.kind == "story":
        return await write_story(post)
    system = SYSTEM_PROMPT.format(shop=_shop(), catalog=await _catalog(session))
    text = await _ask(post, system, await _task(post))
    # AI пишет обычный текст, а пост отправляется как HTML
    return html.escape(text, quote=False) if text else None


async def write_story(post: ChannelPost) -> str | None:
    """Две строки для картинки сторис: заголовок и пояснение. None — AI не ответил или нет товара."""
    if post.product is None:
        return None
    p = post.product
    text = await _ask(post, STORY_PROMPT.format(shop=_shop()), f"Товар: «{p.name}» ({p.category}). {p.description}")
    lines = [line.strip(" «»\"") for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    return f"{lines[0][:STORY_TITLE_LIMIT]}\n{lines[1][:STORY_LINE_LIMIT]}"
