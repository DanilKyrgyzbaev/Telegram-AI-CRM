"""AI-помощник каталога: из длинной карточки Wildberries делает короткое название, категорию и описание."""

import logging
from dataclasses import dataclass

import anthropic

from app.ai.manager import client
from app.config import get_settings
from app.services.wb_cards import WbCard

logger = logging.getLogger(__name__)

PROMPT = """Ты помогаешь заполнить каталог магазина одежды. Ниже карточка товара с Wildberries:
длинное SEO-название, категория WB, описание и характеристики.
Ответь ровно тремя строками без нумерации, кавычек и пояснений:
1-я — короткое понятное название товара для покупателя, до 60 символов (без слов «женский/мужской», если это не важно);
2-я — категория: одна из списка «{categories}», а если ни одна не подходит — новая, коротко, с заглавной буквы;
3-я — описание для AI-консультанта, 1–2 предложения до 200 символов: для кого, крой, материал, чем хорош.
Не выдумывай того, чего нет в карточке."""


@dataclass
class ProductDraft:
    name: str
    category: str
    description: str


def _fallback(card: WbCard) -> ProductDraft:
    return ProductDraft(name=card.name[:255], category=card.subject[:64], description=card.description[:300])


async def product_draft(card: WbCard, categories: list[str]) -> ProductDraft:
    """Поля для нового товара. Если AI не ответил — берём как есть с карточки WB."""
    task = (f"Название: {card.name}\nКатегория WB: {card.subject}\nОписание: {card.description}\n"
            f"Характеристики:\n{card.specs}")
    try:
        response = await client.messages.create(
            model=get_settings().ai_model,
            max_tokens=2048,
            system=PROMPT.format(categories=", ".join(categories) or "—"),
            messages=[{"role": "user", "content": task}],
        )
    except anthropic.APIError:
        logger.exception("Claude API error while drafting product %s", card.article)
        return _fallback(card)
    text = "".join(b.text for b in response.content if b.type == "text")
    lines = [line.strip(" «»\"") for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return _fallback(card)
    return ProductDraft(name=lines[0][:255], category=lines[1][:64], description=lines[2][:500])
