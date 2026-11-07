"""Compact inset grid: once interiors are painted in place, the grid below the world keeps only the interiors that could not be
anchored. The anchored ones keep their size in ``layout.places`` (their pixels come from the ROM, ``InteriorImages``) but sit
at an off-canvas sentinel so nothing hits or draws them in the grid. Pure layout maths + one numpy copy."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw

from pokeagent.atlas.rom_maps import map_name
from pokeagent.atlas.world import CELL, GAP, LABEL, MIN_ROW, Place, WorldLayout

OFF = -100_000                 # sentinel cell coordinate of an interior that is not in the grid
DARK = (28, 28, 36)


def in_grid(layout: WorldLayout, m: int) -> bool:
    p = layout.places.get(m)
    return p is not None and p.interior and p.x != OFF


def compact_layout(layout: WorldLayout, keep: set[int]) -> WorldLayout:
    """``layout`` with the inset grid re-packed for the interiors in ``keep``; the others move off-canvas, the height shrinks."""
    places = {m: p for m, p in layout.places.items() if not p.interior}
    order = sorted((m for m in keep if m in layout.places and layout.places[m].interior), key=lambda m: (layout.places[m].y, layout.places[m].x, m))
    row_w, x, y, row_h = max(layout.width, MIN_ROW), GAP, layout.outdoor_height + GAP, 0
    for m in order:
        p = layout.places[m]
        if x + p.w + GAP > row_w and x > GAP:
            x, y, row_h = GAP, y + row_h + GAP, 0
        places[m] = Place(x, y + LABEL, p.w, p.h, True)
        x, row_h = x + p.w + GAP, max(row_h, p.h + LABEL)
    for m, p in layout.places.items():
        if p.interior and m not in places:
            places[m] = Place(OFF, OFF, p.w, p.h, True)
    height = y + row_h + GAP if order else layout.outdoor_height
    return replace(layout, places=places, height=height, width=layout.width)


def compact_image(base: np.ndarray, old: WorldLayout, new: WorldLayout, keep: set[int]) -> np.ndarray:
    """The outdoor rows of ``base`` plus a re-packed, labelled grid of the ``keep`` interiors (pixels copied from ``old``'s grid)."""
    out = np.empty((new.height * CELL, new.width * CELL, 3), dtype=np.uint8)
    out[:] = DARK
    rows = new.outdoor_height * CELL
    out[:rows] = base[:rows, :out.shape[1]]
    for m in keep:
        if not in_grid(old, m) or not in_grid(new, m):
            continue
        o, n = old.places[m], new.places[m]
        out[n.y * CELL:(n.y + n.h) * CELL, n.x * CELL:(n.x + n.w) * CELL] = base[o.y * CELL:(o.y + o.h) * CELL, o.x * CELL:(o.x + o.w) * CELL]
    pil = Image.fromarray(out)
    dr = ImageDraw.Draw(pil)
    for m in keep:
        if in_grid(new, m):
            p = new.places[m]
            dr.text((p.x * CELL, (p.y - LABEL) * CELL + 2), f"0x{m:02X} {map_name(m)}", fill=(235, 235, 235))
    return np.asarray(pil)
