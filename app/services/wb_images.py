"""Главное фото товара с CDN Wildberries — для постов в канал."""

import asyncio
import io
import logging

import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)

# Фото лежат на серверах basket-01…basket-NN; на каком именно — зависит от артикула и меняется
# по мере роста WB, поэтому сервер не вычисляем, а ищем: опрашиваем все разом и берём ответивший
MAX_BASKET = 80
TIMEOUT = aiohttp.ClientTimeout(total=10)
# Подпись к фото в Telegram — не длиннее 1024 символов
CAPTION_LIMIT = 1024

# Артикул → номер сервера basket, чтобы не искать заново при каждом посте
_baskets: dict[int, int] = {}
# Каждый поиск — 80 запросов разом; сайт-каталог просит много фото одновременно,
# и при параллельных поисках WB перестаёт отвечать — ищем не больше двух за раз
_search_limit = asyncio.Semaphore(2)


def _url(article: int, basket: int) -> str:
    return (
        f"https://basket-{basket:02d}.wbbasket.ru/vol{article // 100000}/part{article // 1000}"
        f"/{article}/images/big/1.webp"
    )


async def _find_basket(http: aiohttp.ClientSession, article: int) -> int | None:
    async with _search_limit:
        # Пока ждали очереди, этот же артикул мог найти другой запрос
        if article in _baskets:
            return _baskets[article]
        return await _probe_all(http, article)


async def _probe_all(http: aiohttp.ClientSession, article: int) -> int | None:
    async def probe(basket: int) -> int | None:
        try:
            async with http.head(_url(article, basket)) as response:
                return basket if response.status == 200 else None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    for basket in await asyncio.gather(*(probe(b) for b in range(1, MAX_BASKET + 1))):
        if basket is not None:
            return basket
    return None


async def basket_for(http: aiohttp.ClientSession, article: int) -> int | None:
    """Номер сервера basket, где лежат файлы товара (запоминается)."""
    basket = _baskets.get(article) or await _find_basket(http, article)
    if basket is not None:
        _baskets[article] = basket
    return basket


async def product_photo(article: int) -> bytes | None:
    """JPEG главного фото товара или None, если фото найти не удалось."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as http:
            basket = _baskets.get(article) or await _find_basket(http, article)
            if basket is None:
                logger.warning("WB photo not found for article %s", article)
                return None
            async with http.get(_url(article, basket)) as response:
                if response.status != 200:
                    _baskets.pop(article, None)
                    return None
                webp = await response.read()
            _baskets[article] = basket
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("WB photo download failed for article %s", article)
        return None

    # WB отдаёт WebP, а Telegram надёжно показывает как фото JPEG
    buffer = io.BytesIO()
    Image.open(io.BytesIO(webp)).convert("RGB").save(buffer, "JPEG", quality=90)
    return buffer.getvalue()
