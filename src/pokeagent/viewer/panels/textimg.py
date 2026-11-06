"""Rasterize styled panel lines into an RGBA float texture (PIL; pure, no UI toolkit).

Dear PyGui textures are the only way to keep per-glyph/per-span colours without one widget
per character, so every text panel renders through here at 2x and lets the GPU downscale.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
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


SEES_GRID = (20, 18)  # (cols, rows): overworld map is 10 wide, battle lines up to 20 chars
_ROW_PX = 16  # default row pitch (display px) when a panel has no explicit grid


def font_px(width: int, height: int, rows: int, cols: int | None = None) -> int:
    """Glyph size (device px) for a fixed ``rows`` x ``cols`` grid in a width x height box.

    Depends only on the box and the grid, never on the lines, so the scale cannot change."""
    h = max(8, height) * _SS
    px = h / rows * 0.72
    if cols:
        px = min(px, max(8, width) * _SS / cols / 0.6)  # monospace advance ~0.6 em
    return max(8, min(44, int(px)))


def fit_lines(lines: list[Line], rows: int, cols: int | None) -> list[Line]:
    """Pad/truncate to the grid: extra rows dropped, long lines cut with an ellipsis."""
    out = []
    for line in lines[:rows]:
        if cols is None:
            out.append(line)
            continue
        left, new = cols, []
        for text, color in line:
            if left <= 0:
                break
            if len(text) > left:
                text = text[:max(0, left - 1)] + "\u2026"
            new.append((text, color))
            left -= len(text)
        out.append(new)
    return out


def lines_texture(lines: list[Line], width: int, height: int, *, bg: str = PANE,
                  grid: tuple[int, int] | None = None) -> tuple[np.ndarray, int, int]:
    """Lines -> (rgba floats 0..1, tex_w, tex_h) on a FIXED character grid.

    ``grid`` is (cols, rows); without it rows = height // 16 and lines are not cut by width.
    The glyph size is a function of the box and grid only (see ``font_px``)."""
    w, h = max(8, width) * _SS, max(8, height) * _SS
    cols, rows = grid if grid else (None, max(1, max(8, height) // _ROW_PX))
    line_h = h / rows
    font = _font(font_px(width, height, rows, cols))
    lines = fit_lines(lines, rows, cols)
    im = Image.new("RGBA", (w, h), _hex_rgb(bg) + (255,))
    draw = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        x = 2
        y = i * line_h
        for text, color in line:
            draw.text((x, y), text, font=font, fill=_hex_rgb(color) + (255,))
            x += int(font.getlength(text)) + 1
    return np.frombuffer(im.tobytes(), dtype=np.uint8).astype(np.float32) / np.float32(255.0), w, h
