"""Draft Moodelle logo variants: font outlines + hand-drawn arch over 'oo' and swash under 'delle'."""
import math
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

SP = Path(sys.argv[1])
OUT = SP / "logo"
WORD = "moodelle"

FONTS = {
    "baskerville": ("LibreBaskerville%5Bwght%5D.ttf", {"wght": 400}),
    "playfair": ("PlayfairDisplay%5Bwght%5D.ttf", {"wght": 400}),
    "gilda": ("GildaDisplay-Regular.ttf", None),
    "cormorant": ("CormorantGaramond%5Bwght%5D.ttf", {"wght": 500}),
    "lora": ("Lora%5Bwght%5D.ttf", {"wght": 400}),
}


def bezier(p, t):
    u = 1 - t
    return (
        u**3 * p[0][0] + 3 * u * u * t * p[1][0] + 3 * u * t * t * p[2][0] + t**3 * p[3][0],
        u**3 * p[0][1] + 3 * u * u * t * p[1][1] + 3 * u * t * t * p[2][1] + t**3 * p[3][1],
    )


def tapered(p, width, steps=80, bias=0.5):
    """Filled brush stroke along a cubic curve: thin at the ends, `width` at its widest."""
    left, right = [], []
    for i in range(steps + 1):
        t = i / steps
        x, y = bezier(p, t)
        x2, y2 = bezier(p, min(t + 1e-3, 1)) if t < 1 else bezier(p, t)
        x1, y1 = bezier(p, max(t - 1e-3, 0))
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1
        nx, ny = -dy / n, dx / n
        # Brush pressure peaks at `bias` along the stroke
        s = t / bias if t < bias else (1 - t) / (1 - bias)
        w = width / 2 * math.sin(s * math.pi / 2) ** 0.8 + 1.5
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    pts = left + right[::-1]
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"


def build(key, file, axes):
    font = TTFont(SP / "fonts" / file)
    if axes:
        font = instancer.instantiateVariableFont(font, axes)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    k = 1000 / upm
    xh = font["OS/2"].sxHeight * k

    paths, boxes, x = [], [], 0.0
    for ch in WORD:
        name = cmap[ord(ch)]
        g = gs[name]
        pen = SVGPathPen(gs)
        # Font units (y up) → SVG (y down), normalised to 1000 per em
        g.draw(TransformPen(pen, (k, 0, 0, -k, x, 0)))
        bp = BoundsPen(gs)
        g.draw(TransformPen(bp, (k, 0, 0, k, x, 0)))
        boxes.append(bp.bounds)
        paths.append(pen.getCommands())
        x += g.width * k
    total = x

    o1, o2 = boxes[1], boxes[2]
    stem = (o1[2] - o1[0]) * 0.11
    # Arch over "oo" — like an eyebrow, from the left of the first o to the right of the second
    ax0, ax1 = o1[0] + (o1[2] - o1[0]) * 0.18, o2[2] - (o2[2] - o2[0]) * 0.18
    top = -(xh + 70)
    arch = tapered(
        [(ax0, top + 20), (ax0 + (ax1 - ax0) * 0.15, top - 190), (ax1 - (ax1 - ax0) * 0.15, top - 190), (ax1, top + 20)],
        stem * 1.1,
    )
    # Swash under "delle": starts at the bowl of d, dips, and lifts past the final e
    d, last = boxes[3], boxes[-1]
    sx0, sx1 = d[0] + (d[2] - d[0]) * 0.15, last[2] + 70
    swash = tapered(
        [(sx0 - 20, 20), (sx0 + 40, 320), (sx1 - 220, 300), (sx1 + 30, -90)],
        stem * 1.4,
        bias=0.38,
    )

    glyphs = " ".join(paths)
    pad = 40
    minx, maxx = min(b[0] for b in boxes) - pad, max(total, sx1) + pad
    miny, maxy = top - 230, 330
    vb = f"{minx:.0f} {miny:.0f} {maxx - minx:.0f} {maxy - miny:.0f}"
    word = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" fill="currentColor">'
        f'<title>Moodelle</title><path d="{glyphs}"/><path d="{arch}"/><path d="{swash}"/></svg>'
    )
    (OUT / f"wordmark-{key}.svg").write_text(word)

    # Monogram for avatars: "m" under its own arch
    m = boxes[0]
    mp = paths[0]
    mx0, mx1 = m[0] + (m[2] - m[0]) * 0.12, m[2] - (m[2] - m[0]) * 0.12
    marc = tapered(
        [(mx0, top + 20), (mx0 + (mx1 - mx0) * 0.1, top - 170), (mx1 - (mx1 - mx0) * 0.1, top - 170), (mx1, top + 20)],
        stem * 0.95,
    )
    cx, cy = (m[0] + m[2]) / 2, (top - 150) / 2 + 10
    r = max(m[2] - m[0], -(top - 170)) * 0.68
    mono = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{cx - r:.0f} {cy - r:.0f} {2 * r:.0f} {2 * r:.0f}" fill="currentColor">'
        f'<title>Moodelle</title><path d="{mp}"/><path d="{marc}"/></svg>'
    )
    (OUT / f"monogram-{key}.svg").write_text(mono)


for key, (file, axes) in FONTS.items():
    build(key, file, axes)
    print("ok", key)
