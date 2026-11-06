"""Smooth movement between two ``move`` events (pure): where an agent is drawn at time ``now``, in world pixels."""
from __future__ import annotations

from pokeagent.atlas.world import CELL, WorldLayout
from pokeagent.world.model import Track

STEP_S = 0.18          # seconds a one-cell move takes on screen
MAX_SLIDE_S = 0.6      # a long jump (events are sampled) never slides longer than this


def progress(moved_at: float, now: float, cells: float) -> float:
    """0..1 along the move; longer moves take longer, capped at MAX_SLIDE_S."""
    dur = min(MAX_SLIDE_S, STEP_S * max(1.0, cells))
    return min(1.0, max(0.0, (now - moved_at) / dur))


def place(t: Track, layout: WorldLayout, now: float) -> tuple[float, float, int] | None:
    """(world px x, world px y, walk phase 0|1|2) of the agent's sprite top-left, or None while unplaced / off the layout."""
    if not t.placed or t.map not in layout.places:
        return None
    x1, y1 = layout.to_world(t.map, t.x, t.y)
    if t.prev is None or t.prev[0] != t.map or t.prev[0] not in layout.places:
        return float(x1), float(y1), 0
    x0, y0 = layout.to_world(*t.prev)
    cells = (abs(x1 - x0) + abs(y1 - y0)) / CELL
    p = progress(t.moved_at, now, cells)
    if p >= 1.0 or cells == 0:
        return float(x1), float(y1), 0
    return x0 + (x1 - x0) * p, y0 + (y1 - y0) * p, 1 + int(p * 4) % 2


def trail_points(t: Track, layout: WorldLayout, n: int = 120) -> list[tuple[int, int]]:
    """Cell centres (world px) of the last ``n`` visited cells that are on the layout, oldest first."""
    pts = []
    for m, x, y in list(t.path)[-n:]:
        if m in layout.places:
            px, py = layout.to_world(m, x, y)
            pts.append((px + CELL // 2, py + CELL // 2))
    return pts
