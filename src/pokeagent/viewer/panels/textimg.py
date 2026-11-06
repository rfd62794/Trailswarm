"""Rasterize styled panel lines into an RGBA float texture (PIL; pure, no UI toolkit).

Dear PyGui textures are the only way to keep per-glyph/per-span colours without one widget
per character, so every text panel renders through here at 2x and lets the GPU downscale.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from pokeagent.viewer.panels import PANE

_SS = 2  # supersample factor: rasterize at 2x, display at 1x


def _hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


@lru_cache(maxsize=8)
def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("consola.ttf", "cour.ttf", "lucon.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:  # older Pillow: load_default() takes no size
        return ImageFont.load_default()


def lines_texture(lines: list[Line], width: int, height: int, *, bg: str = PANE) -> tuple[list[float], int, int]:
    """Lines -> (rgba floats 0..1, tex_w, tex_h). Font size shrinks to fit ``height``."""
    w, h = max(8, width) * _SS, max(8, height) * _SS
    n = max(1, len(lines))
    line_h = h / n
    px = max(12, min(44, int(line_h * 0.72)))  # device px (2x supersampled)
    font = _font(px)
    im = Image.new("RGBA", (w, h), _hex_rgb(bg) + (255,))
    draw = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        x = 2
        y = i * line_h
        for text, color in line:
            draw.text((x, y), text, font=font, fill=_hex_rgb(color) + (255,))
            x += int(font.getlength(text)) + 1
    rgba = im.convert("RGBA").tobytes()
    out: list[float] = []
    ap = out.append
    for j in range(0, len(rgba), 4):
        ap(rgba[j] / 255.0)
        ap(rgba[j + 1] / 255.0)
        ap(rgba[j + 2] / 255.0)
        ap(rgba[j + 3] / 255.0)
    return out, w, h
