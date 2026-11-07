"""Render one map to an RGB numpy image: blocks -> 4x4 tiles of 8x8 pixels, Gen 1 grey palette."""
from __future__ import annotations

import numpy as np

from pokeagent.atlas.rom_maps import MapHeader
from pokeagent.atlas.tiles import GREY, Tileset, block_image

BLOCK_PX, CELL_PX = 32, 16


def shade_to_rgb(shade: np.ndarray) -> np.ndarray:
    g = GREY[shade]
    return np.stack([g, g, g], axis=-1)


def render_blocks(ts: Tileset, blocks: bytes, w: int, h: int, border: int | None = None, pad: int = 0) -> np.ndarray:
    """RGB image of an h x w block grid, with ``pad`` border-block rings around it (pad needs ``border``)."""
    cache: dict[int, np.ndarray] = {}

    def img(b: int) -> np.ndarray:
        if b not in cache:
            cache[b] = block_image(ts, b)
        return cache[b]

    p = pad if border is not None else 0
    shade = np.zeros(((h + 2 * p) * BLOCK_PX, (w + 2 * p) * BLOCK_PX), dtype=np.uint8)
    for by in range(-p, h + p):
        for bx in range(-p, w + p):
            inside = 0 <= bx < w and 0 <= by < h
            bid = blocks[by * w + bx] if inside and by * w + bx < len(blocks) else border
            if bid is None:
                continue
            y0, x0 = (by + p) * BLOCK_PX, (bx + p) * BLOCK_PX
            shade[y0:y0 + BLOCK_PX, x0:x0 + BLOCK_PX] = img(bid)
    return shade_to_rgb(shade)


def render_map(rom: bytes, hd: MapHeader, ts: Tileset, pad: int = 0) -> np.ndarray:
    """RGB image of one map; ``pad`` = rings of border blocks around it (the game shows 3)."""
    return render_blocks(ts, hd.blocks(rom), hd.w, hd.h, hd.border, pad)
