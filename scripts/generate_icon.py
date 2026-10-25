"""Draws the Cicero icon (a wise Roman orator with a white beard and a laurel wreath) into cicero/assets/.

The generated files are committed, so this only needs to run after changing the
design. It needs Pillow (see requirements-dev.txt): ``python scripts/generate_icon.py``
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "cicero" / "assets"

CANVAS = 1024  # drawn large, then scaled down for smooth edges
BACKGROUND_TOP = (112, 62, 176)  # imperial purple
BACKGROUND_BOTTOM = (48, 20, 98)
CREAM = (250, 236, 208)
GOLD = (240, 176, 64)
GOLD_DARK = (176, 116, 30)
SKIN = (238, 196, 156)
SKIN_SHADE = (214, 164, 122)
WHITE = (250, 250, 246)
WHITE_SHADE = (214, 214, 222)
INK = (58, 34, 40)
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

HEAD = (512, 420)  # centre of the face
FACE_SIZE = (330, 400)


def _rounded_background() -> Image.Image:
    column = Image.new("RGBA", (1, CANVAS))
    column.putdata([
        tuple(round(a + (b - a) * y / (CANVAS - 1)) for a, b in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM)) + (255,)
        for y in range(CANVAS)
    ])
    gradient = column.resize((CANVAS, CANVAS), Image.Resampling.NEAREST)
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, CANVAS - 40, CANVAS - 40), radius=210, fill=255)
    background = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    background.paste(gradient, mask=mask)
    return background, mask


def _rotated_ellipse(image: Image.Image, center: tuple[float, float], size: tuple[float, float],
                     angle: float, fill: tuple[int, ...]) -> None:
    """Paste an ellipse of ``size`` rotated by ``angle`` degrees (clockwise) centered on ``center``."""
    width, height = size
    side = int(max(width, height)) + 4
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        ((side - width) / 2, (side - height) / 2, (side + width) / 2, (side + height) / 2), fill=fill
    )
    layer = layer.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
    image.alpha_composite(layer, (int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)))


def _thick_segment(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float],
                   width: float, fill: tuple[int, ...]) -> None:
    """A straight bar with rounded ends."""
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    dx, dy = math.sin(angle) * width / 2, -math.cos(angle) * width / 2
    draw.polygon(
        [(start[0] + dx, start[1] + dy), (end[0] + dx, end[1] + dy),
         (end[0] - dx, end[1] - dy), (start[0] - dx, start[1] - dy)],
        fill=fill,
    )
    for x, y in (start, end):
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=fill)


def _toga(draw: ImageDraw.ImageDraw) -> None:
    """Shoulders draped in a cream toga with the purple stripe of a Roman senator."""
    draw.ellipse((150, 760, 874, 1240), fill=CREAM)
    draw.line([(300, 790), (520, 1000)], fill=BACKGROUND_TOP, width=46)  # stripe over the left shoulder
    draw.line([(724, 790), (520, 1000)], fill=GOLD_DARK, width=18)


def _hair(image: Image.Image) -> None:
    """Balding on top, white hair at the sides and back."""
    cx, cy = HEAD
    for side in (-1, 1):
        _rotated_ellipse(image, (cx + side * 166, cy + 10), (120, 220), side * 10, WHITE_SHADE)
        _rotated_ellipse(image, (cx + side * 160, cy + 0), (116, 214), side * 10, WHITE)
        _rotated_ellipse(image, (cx + side * 182, cy + 90), (96, 160), side * -8, WHITE)


def _laurel(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """A gold wreath around the head from the temples to the crown, open at the top."""
    cx, cy = HEAD
    rx, ry = 186, 196
    center_y = cy - 40
    for side in (-1, 1):
        degrees = [195, 172, 150, 128, 108] if side < 0 else [-15, 8, 30, 52, 72]
        # The stem.
        box = (cx - rx, center_y - ry, cx + rx, center_y + ry)
        start, end = (360 - 195, 360 - 108) if side < 0 else (360 - 72, 360 + 15)
        draw.arc(box, start, end, fill=GOLD_DARK, width=14)
        for index, angle in enumerate(degrees):
            t = math.radians(angle)
            x, y = cx + rx * math.cos(t), center_y - ry * math.sin(t)
            # Direction of the stem towards the crown, as a screen angle.
            dx, dy = (rx * math.sin(t), ry * math.cos(t)) if side < 0 else (-rx * math.sin(t), -ry * math.cos(t))
            direction = math.degrees(math.atan2(dy, dx))
            for flip in (-1, 1):  # a pair of leaves either side of the stem
                normal = math.radians(direction + 90 * flip)
                lx, ly = x + 24 * math.cos(normal), y + 24 * math.sin(normal)
                rotation = direction + 90 + flip * 28
                _rotated_ellipse(image, (lx, ly), (40, 98), rotation, GOLD_DARK)
                _rotated_ellipse(image, (lx, ly), (30, 86), rotation, GOLD)


def _face(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    cx, cy = HEAD
    width, height = FACE_SIZE
    draw.ellipse((cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2), fill=SKIN)
    # Ears, half hidden by the hair.
    for side in (-1, 1):
        _rotated_ellipse(image, (cx + side * 168, cy + 20), (60, 100), 0, SKIN_SHADE)
    # Forehead lines of a thinker.
    for row, half in ((0, 70), (1, 56)):
        y = cy - 128 + row * 30
        draw.arc((cx - half, y - 20, cx + half, y + 20), 200, 340, fill=SKIN_SHADE, width=10)
    # Bushy white eyebrows, raised a little at the outer ends.
    for side in (-1, 1):
        _thick_segment(draw, (cx + side * 30, cy - 46), (cx + side * 122, cy - 70), 40, WHITE_SHADE)
        _thick_segment(draw, (cx + side * 30, cy - 50), (cx + side * 122, cy - 74), 36, WHITE)
    # Calm, half-closed eyes.
    for side in (-1, 1):
        ex = cx + side * 76
        draw.arc((ex - 36, cy - 34, ex + 36, cy + 10), 20, 160, fill=INK, width=14)


def _beard(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """A long, curly white beard and moustache."""
    cx, cy = HEAD
    # Body of the beard: from the cheeks down to a rounded point.
    outline = [(cx - 172, cy + 56), (cx + 172, cy + 56), (cx + 196, cy + 190), (cx + 150, cy + 330),
               (cx + 70, cy + 430), (cx, cy + 462), (cx - 70, cy + 430), (cx - 150, cy + 330), (cx - 196, cy + 190)]
    draw.polygon(outline, fill=WHITE)
    draw.ellipse((cx - 196, cy + 46, cx + 196, cy + 330), fill=WHITE)
    # Curls along the edge, shaded underneath so they read as separate locks.
    curls = [(-190, 220), (-170, 300), (-130, 370), (-78, 425), (0, 455), (78, 425), (130, 370), (170, 300),
             (190, 220)]
    for dx, dy in curls:
        draw.ellipse((cx + dx - 62, cy + dy - 50, cx + dx + 62, cy + dy + 62), fill=WHITE_SHADE)
    for dx, dy in curls:
        draw.ellipse((cx + dx - 60, cy + dy - 58, cx + dx + 60, cy + dy + 48), fill=WHITE)
    # Strands flowing down.
    for dx in (-120, -60, 0, 60, 120):
        draw.arc((cx + dx - 70, cy + 170, cx + dx + 30, cy + 420), 300, 60, fill=WHITE_SHADE, width=10)
    # Nose, then the moustache under it.
    draw.polygon([(cx - 4, cy - 34), (cx - 36, cy + 80), (cx + 32, cy + 80)], fill=SKIN_SHADE)
    draw.ellipse((cx - 36, cy + 62, cx + 32, cy + 92), fill=SKIN_SHADE)
    for side in (-1, 1):
        _rotated_ellipse(image, (cx + side * 56, cy + 122), (140, 62), side * -16, WHITE_SHADE)
        _rotated_ellipse(image, (cx + side * 56, cy + 114), (136, 58), side * -16, WHITE)


def draw_icon() -> Image.Image:
    background, mask = _rounded_background()
    figure = Image.new("RGBA", background.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(figure)
    _toga(draw)
    _hair(figure)
    _face(figure, draw)
    _beard(figure, draw)
    _laurel(figure, draw)
    clipped = Image.new("RGBA", background.size, (0, 0, 0, 0))
    clipped.paste(figure, mask=mask)  # keep the toga inside the rounded tile
    background.alpha_composite(clipped)
    return background


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_icon()
    master.resize((256, 256), Image.Resampling.LANCZOS).save(ASSETS / "cicero.png")
    for size in (48, 64):
        master.resize((size, size), Image.Resampling.LANCZOS).save(ASSETS / f"cicero-{size}.png")
    master.save(ASSETS / "cicero.ico", sizes=[(s, s) for s in ICO_SIZES])
    print(f"Icons written to {ASSETS}")


if __name__ == "__main__":
    main()
