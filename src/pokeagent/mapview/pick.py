"""Click-to-agent hit testing for the stitched map (pure: no UI toolkit).

``heads`` lists where the overlay drew each head this frame (screen pixels) so a click can be
turned into an ``(agent, kind)`` pick without any per-head Dear PyGui items.
"""
from __future__ import annotations

import math

import numpy as np

from pokeagent.mapview.overlay import _offsets
from pokeagent.mapview.playback import Frame, Tables

CLICK_PX = 4.0          # a press+release within this distance counts as a click, not a drag
PICK_RADIUS = 10.0      # how close to a drawn head a click must land to hit it


def is_click(down, up) -> bool:
    """Press and release within ``CLICK_PX`` on both axes; a drag never selects."""
    if down is None or up is None:
        return False
    return abs(up[0] - down[0]) < CLICK_PX and abs(up[1] - down[1]) < CLICK_PX


def heads(frame: Frame, tb: Tables, layout, rect, zoom: float,
          live=None) -> list[tuple[str, str, float, float]]:
    """``(agent, kind, screen_x, screen_y)`` per head ``render`` draws inside ``rect`` —
    ``"live"`` for live agents, ``"ghost"`` for replayed runs (``live``: the same
    ``(agent, x, y, facing, phase)`` tuples ``render`` gets, in space coordinates)."""
    x0, y0, x1, y1 = rect
    w, h = max(1, int(round((x1 - x0) * zoom))), max(1, int(round((y1 - y0) * zoom)))
    out: list[tuple[str, str, float, float]] = []
    if len(tb.ghosts) and tb.area_names:
        ox, oy, known = _offsets(tb, layout)
        ai = np.clip(frame.area.astype(np.intp), 0, len(known) - 1)
        ok = (frame.area >= 0) & (frame.area < len(known)) & known[ai]
        hx = (ox[ai] + frame.xs - x0) * zoom
        hy = (oy[ai] + frame.ys - y0) * zoom
        for k in np.flatnonzero(ok & (hx >= 0) & (hx < w) & (hy >= 0) & (hy < h)):
            out.append((str(tb.agents[k]), "ghost", float(hx[k]), float(hy[k])))
    for agent, lx, ly, _f, _ph in live or ():
        px, py = (lx - x0) * zoom, (ly - y0) * zoom
        if 0 <= px < w and 0 <= py < h and math.isfinite(px) and math.isfinite(py):
            out.append((str(agent), "live", float(px), float(py)))
    return out


def pick_agent(px: float, py: float, drawn: list[tuple[str, str, float, float]],
               radius: float = PICK_RADIUS) -> tuple[str, str] | None:
    """``(agent, kind)`` of the head nearest ``(px, py)`` within ``radius``, else None. ``drawn``
    rows are ``(agent, kind, screen_x, screen_y)``; "live" wins a distance tie over "ghost"."""
    best = None
    for agent, kind, sx, sy in drawn:
        d = (sx - px) * (sx - px) + (sy - py) * (sy - py)
        key = (d, 0 if kind == "live" else 1)
        if d <= radius * radius and (best is None or key < best[0]):
            best = (key, agent, kind)
    return (best[1], best[2]) if best is not None else None
