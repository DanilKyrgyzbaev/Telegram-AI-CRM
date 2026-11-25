"""Данные товара с карточки Wildberries: название, описание, состав, таблица размеров.

Карточка лежит на том же CDN, что и фото (basket-NN.wbbasket.ru/…/info/ru/card.json). Цены там нет —
её WB отдаёт только своему сайту, поэтому цену вводит админ.
"""

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

from app.services.wb_images import TIMEOUT, basket_for

logger = logging.getLogger(__name__)

# Характеристики, полезные покупателю при выборе; остальное (ТНВЭД, комплектация и т. п.) не берём
SPEC_NAMES = (
    "Состав", "Пол", "Сезон", "Температурный режим", "Утеплитель", "Материал подкладки", "Посадка",
    "Фактура материала", "Тип карманов", "Вид застежки", "Покрой", "Модель брюк", "Модель костюма", "Рост модели на фото",
)
DESCRIPTION_LIMIT = 1500


async def refresh_product(product) -> bool:
    """Обновляет характеристики и таблицу размеров товара с карточки WB. Название, описание и цену не трогает."""
    if not product.wb_article:
        return False
    card = await fetch_card(product.wb_article)
    if card is None:
        return False
    product.specs, product.size_chart = card.specs, card.size_chart
    return True


@dataclass
class WbCard:
    article: int
    name: str
    subject: str
    description: str
    specs: str
    size_chart: str


def _specs(card: dict) -> str:
    options = {o.get("name"): o.get("value") for o in card.get("options", []) if o.get("name") and o.get("value")}
    return "\n".join(f"{name}: {options[name]}" for name in SPEC_NAMES if name in options)


def _size_chart(card: dict) -> str:
    """«S: RU 46-48, Обхват талии 78-86 см, …» — по строке на размер, от меньшего к большему."""
    table = card.get("sizes_table") or {}
    props = table.get("details_props") or []
    rows = []
    for size in table.get("values") or []:
        cells = [f"{prop.replace(', в см', '')} {value}" for prop, value in zip(props, size.get("details") or []) if value]
        rows.append(((size.get("details") or [""])[0], f"{size.get('tech_size')}: {', '.join(cells)}"))
    return "\n".join(row for _, row in sorted(rows, key=lambda r: r[0]))


async def fetch_card(article: int) -> WbCard | None:
    """Карточка товара или None, если WB её не отдал."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as http:
            basket = await basket_for(http, article)
            if basket is None:
                return None
            url = (f"https://basket-{basket:02d}.wbbasket.ru/vol{article // 100000}/part{article // 1000}"
                   f"/{article}/info/ru/card.json")
            async with http.get(url) as response:
                if response.status != 200:
                    return None
                card = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        logger.exception("WB card %s download failed", article)
        return None
    return WbCard(
        article=article,
        name=card.get("imt_name") or "",
        subject=card.get("subj_name") or "",
        description=(card.get("description") or "")[:DESCRIPTION_LIMIT],
        specs=_specs(card),
        size_chart=_size_chart(card),
    )
