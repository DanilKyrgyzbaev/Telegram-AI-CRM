"""Картинка для сторис Instagram 1080×1920: логотип, фото товара, текст от AI и цена."""

import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models import ChannelPost
from app.services.wb_images import product_photo

ASSETS = Path(__file__).resolve().parent.parent
FONT = ASSETS / "assets" / "fonts" / "Manrope.ttf"
LOGO = ASSETS / "site" / "static" / "logo.png"

WIDTH, HEIGHT = 1080, 1920
CREAM, INK, MUTED, ACCENT, WHITE = "#f6f2ec", "#1d1a17", "#6f675e", "#8a2bb0", "#ffffff"
PHOTO_WIDTH, PHOTO_MAX_HEIGHT = 820, 960
# Нижние ~200 px сторис закрывает поле ответа Instagram — туда ничего не ставим
FOOTER_Y = 1700

# Готовые картинки по ID поста и тексту: Instagram скачивает картинку при публикации, админ — в превью
_cache: dict[tuple[int, str], bytes] = {}


def _font(size: int, weight: str) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT), size)
    font.set_variation_by_name(weight)
    return font


def _rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *image.size), radius=radius, fill=255)
    image.putalpha(mask)
    return image


def _centered_lines(draw: ImageDraw.ImageDraw, y: int, lines: list[str], font, fill, spacing: int) -> int:
    for line in lines:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        draw.text(((WIDTH - (right - left)) / 2 - left, y - top), line, font=font, fill=fill)
        y += bottom - top + spacing
    return y


def _price(value) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


def compose(photo_jpeg: bytes, title: str, line: str, price) -> bytes:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), CREAM)

    logo = Image.open(LOGO)
    logo_width = 340
    logo = logo.resize((logo_width, logo.height * logo_width // logo.width), Image.LANCZOS)
    canvas.paste(logo, ((WIDTH - logo_width) // 2, 80), logo)

    photo = Image.open(io.BytesIO(photo_jpeg)).convert("RGBA")
    photo_height = photo.height * PHOTO_WIDTH // photo.width
    photo = photo.resize((PHOTO_WIDTH, photo_height), Image.LANCZOS)
    # Высокое фото обрезаем сверху и снизу поровну, чтобы осталось место для текста
    if photo_height > PHOTO_MAX_HEIGHT:
        top = (photo_height - PHOTO_MAX_HEIGHT) // 2
        photo, photo_height = photo.crop((0, top, PHOTO_WIDTH, top + PHOTO_MAX_HEIGHT)), PHOTO_MAX_HEIGHT
    photo = _rounded(photo, 36)
    canvas.paste(photo, ((WIDTH - PHOTO_WIDTH) // 2, 230), photo)

    draw = ImageDraw.Draw(canvas)
    y = 230 + photo_height + 48
    y = _centered_lines(draw, y, textwrap.wrap(title, 24), _font(62, "Bold"), INK, 12) + 14
    y = _centered_lines(draw, y, textwrap.wrap(line, 42), _font(38, "Medium"), MUTED, 10) + 30

    price_font = _font(54, "Bold")
    text = _price(price)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=price_font)
    pill_w, pill_h = right - left + 80, bottom - top + 40
    pill_x = (WIDTH - pill_w) // 2
    y = min(y, FOOTER_Y - pill_h - 30)
    draw.rounded_rectangle((pill_x, y, pill_x + pill_w, y + pill_h), radius=pill_h // 2, fill=ACCENT)
    draw.text((pill_x + 40 - left, y + 20 - top), text, font=price_font, fill=WHITE)

    _centered_lines(draw, FOOTER_Y, ["Ищите на Wildberries · moodelle.store"], _font(34, "SemiBold"), INK, 0)

    buffer = io.BytesIO()
    canvas.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


async def story_image(post: ChannelPost) -> bytes | None:
    """JPEG сторис или None, если у поста нет товара, текста или фото на WB."""
    if post.product is None or not post.product.wb_article or "\n" not in post.text:
        return None
    key = (post.id, post.text)
    if key not in _cache:
        photo = await product_photo(post.product.wb_article)
        if photo is None:
            return None
        title, line = post.text.split("\n", 1)
        _cache[key] = compose(photo, title, line, post.product.price)
    return _cache[key]
