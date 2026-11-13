"""Paint a WorldLayout from the ROM: outdoor maps on a border-block backdrop, labelled interior insets, door links."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from pokeagent.atlas.render import BLOCK_PX, render_blocks, render_map
from pokeagent.atlas.rom_maps import MapHeader, map_name
from pokeagent.world import names
from pokeagent.atlas.tiles import Tileset, load_tileset
from pokeagent.atlas.world import CELL, LABEL, WorldLayout

DARK = (28, 28, 36)
LINK = (230, 120, 20)


def _backdrop(rom: bytes, hd: MapHeader, ts: Tileset, w_px: int, h_px: int) -> np.ndarray:
    one = render_blocks(ts, bytes([hd.border]), 1, 1)
    return np.tile(one, (h_px // BLOCK_PX + 1, w_px // BLOCK_PX + 1, 1))[:h_px, :w_px]


def render_world(rom: bytes, headers: dict[int, MapHeader], layout: WorldLayout, links: bool = True) -> np.ndarray:
    w_px, h_px = layout.size_px
    out_px = layout.outdoor_height * CELL
    cache: dict[int, Tileset] = {}

    def tset(i: int) -> Tileset:
        if i not in cache:
            cache[i] = load_tileset(rom, i)
        return cache[i]

    img = np.empty((h_px, w_px, 3), dtype=np.uint8)
    img[:] = DARK
    home = headers[0]
    img[:out_px] = _backdrop(rom, home, tset(home.tileset), w_px, out_px)
    for m, p in layout.places.items():
        hd = headers[m]
        tile = render_map(rom, hd, tset(hd.tileset))
        img[p.y * CELL:p.y * CELL + tile.shape[0], p.x * CELL:p.x * CELL + tile.shape[1]] = tile
    pil = Image.fromarray(img)
    dr = ImageDraw.Draw(pil)
    for m, p in layout.places.items():
        if p.interior:
            dr.text((p.x * CELL, (p.y - LABEL) * CELL + 2), names.label_for(map_name(m), names.column_px(p.w, CELL)), fill=(235, 245, 200))
    if links:
        for m, (par, x, y) in layout.entrances.items():
            if m in layout.places and par in layout.places and not layout.places[par].interior:
                px, py = layout.to_world(par, x, y)
                q = layout.places[m]
                dr.line([(px + CELL // 2, py + CELL // 2), (q.x * CELL, (q.y - LABEL) * CELL)], fill=LINK, width=1)
    return np.asarray(pil)
