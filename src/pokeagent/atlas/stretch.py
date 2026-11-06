"""Stretch layout: grow the outdoor world locally so every in-place interior fits its building at full size (pure + numpy)."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

import numpy as np

from pokeagent.atlas.anchor import Anchor
from pokeagent.atlas.fit import footprint
from pokeagent.atlas.warp import AxisWarp, Warp, merge_inserts, resample
from pokeagent.atlas.world import CELL, WorldLayout

MAX_EXTRA = 8                  # most cells one building may add per axis


def _bump(ins: dict[int, int], lo: int, hi: int, need: int) -> None:
    """Make the inserts inside [lo, hi) total at least ``need``: top up the best existing one there, else add at the middle."""
    have = [p for p in ins if lo <= p < hi]
    if have:
        p = max(have, key=lambda q: ins[q])
        ins[p] = max(ins[p], need)
    else:
        ins[(lo + hi) // 2] = need


def stretch_warp(anchors: dict[int, Anchor], layout: WorldLayout, walk_of: Callable[[int], np.ndarray | None],
                 bands: dict[str, dict[int, int]] | None = None) -> Warp:
    """The warp that gives every building footprint its interior's full width/height (shared columns/rows share the space)."""
    xs: dict[int, int] = {}
    ys: dict[int, int] = {}
    roots = sorted((a for a in anchors.values() if a.parent not in anchors), key=lambda a: (a.parent, a.via[1], a.via[0]))
    for a in roots:
        par, p = layout.places[a.parent], layout.places[a.map]
        x0, y0, x1, y1 = footprint(walk_of(a.parent), a.via)
        wneed, hneed = min(MAX_EXTRA, max(0, p.w - (x1 - x0))), min(MAX_EXTRA, max(0, p.h - (y1 - y0)))
        if wneed:
            _bump(xs, par.x + x0, par.x + x1, wneed)
        if hneed:
            _bump(ys, par.y + y0, par.y + y1, hneed)
    b = bands or {}
    return Warp(AxisWarp(merge_inserts(xs, b.get("x", {}))), AxisWarp(merge_inserts(ys, b.get("y", {}))))


def stretch_layout(layout: WorldLayout, warp: Warp) -> WorldLayout:
    """``layout`` for the stretched canvas: outdoor places stay logical (``warp`` maps them), the inset grid moves down."""
    dy, dx = warp.y.total, warp.x.total
    places = {m: (replace(p, y=p.y + dy) if p.interior else p) for m, p in layout.places.items()}
    return replace(layout, places=places, width=layout.width + dx, height=layout.height + dy,
                   outdoor_height=layout.outdoor_height + dy, warp=warp)


def stretch_image(base: np.ndarray, layout: WorldLayout, warp: Warp) -> np.ndarray:
    """The stretched outdoor image with the inset grid appended unchanged below (left aligned). ``layout`` is the original."""
    rows = layout.outdoor_height
    top = resample(base[:rows * CELL], warp, rows)
    rest = base[rows * CELL:]
    out = np.empty((top.shape[0] + rest.shape[0], max(top.shape[1], rest.shape[1]), 3), dtype=np.uint8)
    out[:] = (28, 28, 36)
    out[:top.shape[0], :top.shape[1]] = top
    out[top.shape[0]:, :rest.shape[1]] = rest
    return out
