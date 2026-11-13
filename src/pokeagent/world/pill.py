"""Agent label pill geometry (pure): a dark rounded plate offset above the sprite, scaled with the zoom."""
from __future__ import annotations

from typing import NamedTuple

LIFT = 6          # 1x px between the sprite's top edge and the pill's bottom
MIN_K, MAX_K = 0.75, 2.0   # the pill scales with zoom, but stays readable far out and sane close up
PILL_FILL = (14, 24, 14, 215)
PILL_TEXT = (240, 248, 225, 255)


class Pill(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float
    radius: float
    text_x: float
    text_y: float
    font: float


def zoom_k(zoom: float) -> float:
    return max(MIN_K, min(MAX_K, zoom ** 0.5))


def pill(cx: float, top: float, text_w: float, text_h: float, zoom: float = 1.0, pad: float = 3.0) -> Pill:
    """The pill for a label of ``text_w`` x ``text_h`` (1x px), centred on ``cx`` and standing LIFT above ``top`` (the sprite's
    top edge). Everything scales with ``zoom_k``; the radius is half the height (a full capsule)."""
    k = zoom_k(zoom)
    w, h, p = (text_w + 2 * pad) * k, (text_h + 2 * pad) * k, pad * k
    x0, y1 = cx - w / 2, top - LIFT * k
    return Pill(x0, y1 - h, x0 + w, y1, h / 2, x0 + p, y1 - h + p, text_h * k)
