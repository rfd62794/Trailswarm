"""Paint in-place interiors over the outdoor image (numpy/Pillow): dimmed backdrop, drop shadow, depth-tinted frame."""
from __future__ import annotations

import numpy as np
from PIL import Image

from pokeagent.atlas.anchor import Anchor
from pokeagent.atlas.inplace import z_order
from pokeagent.atlas.world import CELL, WorldLayout, Xform

DIM = 0.5
SHADOW = (6, 6, 0.45)                  # dx, dy px, brightness kept under the shadow
FRAMES = ((255, 200, 60), (90, 200, 255), (255, 110, 200), (140, 255, 120))     # by depth - 1


def interior_tile(base: np.ndarray, layout: WorldLayout, m: int, s: float, depth: int) -> np.ndarray:
    """The interior's pixels from the inset grid, scaled by ``s``, tinted darker per floor depth, with its frame."""
    p = layout.places[m]
    src = base[p.y * CELL:(p.y + p.h) * CELL, p.x * CELL:(p.x + p.w) * CELL]
    if s != 1.0:
        w, h = max(1, round(src.shape[1] * s)), max(1, round(src.shape[0] * s))
        src = np.asarray(Image.fromarray(np.ascontiguousarray(src)).resize((w, h), Image.BOX))
    out = (src * max(0.55, 1.0 - 0.12 * (depth - 1))).astype(np.uint8)
    col = np.array(FRAMES[min(depth, len(FRAMES)) - 1], dtype=np.uint8)
    out[:2], out[-2:], out[:, :2], out[:, -2:] = col, col, col, col
    return out


def _win(x: int, y: int, w: int, h: int, W: int, H: int):
    """Clip a w x h rectangle at (x, y) to a W x H canvas: (dst y0, y1, x0, x1, src y0, x0) or None."""
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    return None if x1 <= x0 or y1 <= y0 else (y0, y1, x0, x1, y0 - y, x0 - x)


def compose(base: np.ndarray, layout: WorldLayout, anchors: dict[int, Anchor], shown: set[int], top: int | None = None,
            crop: tuple[int, int, int, int] | None = None, dim: float = DIM) -> np.ndarray:
    """``base`` (or its ``crop`` x0, y0, x1, y1 px) with the shown interiors painted where ``layout.xf`` puts them.
    ``layout`` is the in-place view layout; its ``places`` still hold the inset grid the pixels are read from."""
    x0, y0, x1, y1 = crop or (0, 0, base.shape[1], base.shape[0])
    img = base[y0:y1, x0:x1].copy()
    order = [m for m in z_order(anchors, shown, top) if m in layout.xf]
    if not order:
        return img
    rows = max(0, min(img.shape[0], layout.outdoor_height * CELL - y0))
    img[:rows] = (img[:rows] * dim).astype(np.uint8)
    for m in order:
        t: Xform = layout.xf[m]
        tile = interior_tile(base, layout, m, t.s, anchors[m].depth)
        px, py = round(t.ox * CELL) - x0, round(t.oy * CELL) - y0
        sh = _win(px + SHADOW[0], py + SHADOW[1], tile.shape[1], tile.shape[0], img.shape[1], img.shape[0])
        if sh:
            img[sh[0]:sh[1], sh[2]:sh[3]] = (img[sh[0]:sh[1], sh[2]:sh[3]] * SHADOW[2]).astype(np.uint8)
        w = _win(px, py, tile.shape[1], tile.shape[0], img.shape[1], img.shape[0])
        if w:
            img[w[0]:w[1], w[2]:w[3]] = tile[w[4]:w[4] + w[1] - w[0], w[5]:w[5] + w[3] - w[2]]
    return img
