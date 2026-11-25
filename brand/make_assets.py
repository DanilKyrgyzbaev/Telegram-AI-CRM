"""Картинки бренда из оригинального логотипа brand/logo-original.jpeg (чёрный на белом).

.venv/bin/python brand/make_assets.py → brand/*.png, brand/avatars/*.png и копии для сайта в app/site/static/
"""

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

BRAND = Path(__file__).parent
AVATARS = BRAND / "avatars"
SITE_STATIC = BRAND.parent / "app" / "site" / "static"
INK, CREAM, WHITE = (29, 26, 23), (246, 242, 236), (255, 255, 255)
# Пиксели светлее этого порога считаем фоном; переход к чёрному сохраняет сглаживание краёв
BACKGROUND_LEVEL = 40
# «oo» с дугой — фирменная деталь логотипа для значка вкладки (координаты в обрезанном logo.png)
OO_BOX = (224, 0, 470, 262)


def logo_alpha() -> Image.Image:
    darkness = ImageOps.invert(Image.open(BRAND / "logo-original.jpeg").convert("L"))
    alpha = darkness.point(lambda v: 0 if v < BACKGROUND_LEVEL else min(255, (v - BACKGROUND_LEVEL) * 255 // 175))
    left, top, right, bottom = alpha.getbbox()
    pad = 12
    return alpha.crop((left - pad, top - pad, right + pad, bottom + pad))


def painted(alpha: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", alpha.size, color + (255,))
    image.putalpha(alpha)
    return image


def centered(alpha: Image.Image, size: int, background, color, width_ratio: float) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background + (255,))
    width = int(size * width_ratio)
    height = int(alpha.height * width / alpha.width)
    mark = painted(alpha.resize((width, height), Image.LANCZOS), color)
    canvas.paste(mark, ((size - width) // 2, (size - height) // 2), mark)
    return canvas


def round_icon(alpha: Image.Image, size: int) -> Image.Image:
    icon = centered(alpha, size, INK, CREAM, 0.6)
    circle = Image.new("L", (size, size), 0)
    ImageDraw.Draw(circle).ellipse((0, 0, size, size), fill=255)
    icon.putalpha(circle)
    return icon


def main() -> None:
    AVATARS.mkdir(exist_ok=True)
    alpha = logo_alpha()
    painted(alpha, INK).save(BRAND / "logo.png")
    # Для тёмного бокового меню админки
    painted(alpha, CREAM).save(BRAND / "logo-light.png")

    # Аватарки обрезаются кругом: слово держим в пределах ~78% ширины
    centered(alpha, 1080, WHITE, INK, 0.78).convert("RGB").save(AVATARS / "logo-light.png")
    centered(alpha, 1080, INK, CREAM, 0.78).convert("RGB").save(AVATARS / "logo-dark.png")

    oo = alpha.crop(OO_BOX)
    # Срезаем засечки соседних букв m и d у базовой линии
    pixels = oo.load()
    for x in range(oo.width):
        for y in range(200, oo.height):
            if x < 6 or x > oo.width - 4:
                pixels[x, y] = 0
    oo = oo.crop(oo.getbbox())
    round_icon(oo, 512).save(AVATARS / "favicon.png")
    round_icon(oo, 180).save(AVATARS / "apple-touch-icon.png")

    for source in (BRAND / "logo.png", BRAND / "logo-light.png", AVATARS / "favicon.png", AVATARS / "apple-touch-icon.png"):
        shutil.copy(source, SITE_STATIC / source.name)


if __name__ == "__main__":
    main()
