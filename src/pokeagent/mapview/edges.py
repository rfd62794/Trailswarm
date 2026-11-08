"""Coloured edge lines around stacked areas, drawn once into the static base image.

Pure numpy and deterministic. ``areas_layout`` rows are ``(name, x, y, w, h)`` in index
order (``rects`` builds them from the areas plus the layout); colours cycle the preset
palette with a fix-up so no two neighbouring areas share a colour.
"""
from __future__ import annotations

import numpy as np


def rects(areas, layout) -> list[tuple[str, int, int, int, int]]:
    """(name, x, y, w, h) per placed area, in index order."""
    return [(a.name, *layout.offsets[a.name], a.width, a.height)
            for a in areas if a.name in layout.offsets]


def edge_colours(areas_layout, palette) -> dict[str, str]:
    """One colour per area: the palette in index order, fixed up so no area shares its
    colour with the previous/next index neighbour or the area directly above/below it
    (overlapping span, nearest row). Repeats only when the palette cannot avoid it."""
    pal = list(dict.fromkeys(str(c) for c in palette))
    boxes = [(n, x, y, x + w, y + h) for n, x, y, w, h in areas_layout]
    if not pal or not boxes:
        return {}
    above, below = {}, {}
    for i, (_n, x0, y0, x1, y1) in enumerate(boxes):
        for j, (_m, a0, b0, _a1, b1) in enumerate(boxes):
            if i == j or not (x0 < boxes[j][3] and a0 < x1):
                continue
            if b1 <= y0 and (i not in above or above[i][1] < b1):
                above[i] = (j, b1)
            if y1 <= b0 and (i not in below or below[i][1] > b0):
                below[i] = (j, b0)
    out: list[str] = []
    for i in range(len(boxes)):
        neigh = {j for j in (i - 1,) if j >= 0} | {d[i][0] for d in (above, below) if i in d and d[i][0] < i}
        used = {out[j] for j in neigh}
        pick = pal[i % len(pal)]
        if pick in used:
            pick = next((c for c in pal if c not in used), None)
            if pick is None and i > 0:
                pick = next((c for c in pal if c != out[i - 1]), pal[i % len(pal)])
            if pick is None:
                pick = pal[i % len(pal)]
        out.append(pick)
    return {boxes[i][0]: out[i] for i in range(len(boxes))}


def draw_edges(base: np.ndarray, areas_layout, colours: dict[str, str], width: int = 2) -> None:
    """A ``width``-px rectangle outline in each area's colour just outside the image
    bounds (the gap, never on the image pixels), clipped to the base. An empty colour
    table - a gap of 0 - draws nothing."""
    if width <= 0 or not colours:
        return
    H, W = base.shape[:2]
    for name, x, y, w, h in areas_layout:
        c = colours.get(name)
        if not c:
            continue
        try:
            rgb = np.frombuffer(bytes.fromhex(str(c).lstrip("#")), np.uint8)[:3]
        except ValueError:
            continue
        x0, y0, x1, y1 = x - width, y - width, x + w + width, y + h + width
        spans = ((y0, y0 + width, x0, x1), (y1 - width, y1, x0, x1),
                 (y0 + width, y1 - width, x0, x0 + width), (y0 + width, y1 - width, x1 - width, x1))
        for ya, yb, xa, xb in spans:
            ya, yb, xa, xb = max(0, ya), min(H, yb), max(0, xa), min(W, xb)
            if ya < yb and xa < xb:
                base[ya:yb, xa:xb, :3] = rgb
