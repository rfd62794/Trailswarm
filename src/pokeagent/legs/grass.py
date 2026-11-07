"""Grass walking for the grind drill: the cheapest route to the nearest grass tile, and pacing on grass (ROM grid, no emulator)."""
from __future__ import annotations

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
NEAREST = 25   # grass tiles tried (by distance) when looking for the nearest reachable one
FLIP = {"LEFT": "RIGHT", "RIGHT": "LEFT", "UP": "DOWN", "DOWN": "UP"}


def _ok(g, x: int, y: int) -> bool:
    return g.inside(x, y) and bool(g.walk[y, x]) and (x, y) not in g.solid


def pace_button(g, pos: tuple, heading: str) -> tuple[str, str] | None:
    """(button, new heading) to keep moving on grass from ``pos``: straight on while the next tile is grass, else turn round,
    else any grass neighbour. None when boxed in."""
    x, y = pos
    for h in (heading, FLIP[heading], *(d for d in DIRS if d not in (heading, FLIP[heading]))):
        dx, dy = DIRS[h]
        if _ok(g, x + dx, y + dy) and g.grass[y + dy, x + dx]:
            return h, h
    return None


def to_grass(g, pos: tuple) -> list[str]:
    """Buttons along the cheapest route to the nearest reachable grass tile ([] when none)."""
    from pokeagent.legs.par import par
    ys, xs = (g.grass & g.walk).nonzero()
    cands = sorted(zip(xs.tolist(), ys.tolist()), key=lambda c: abs(c[0] - pos[0]) + abs(c[1] - pos[1]))[:NEAREST]
    best = None
    for c in cands:
        r = par(g, pos, c)
        if r and (best is None or r[0] < best[0]):
            best = r
    if not best:
        return []
    names = {v: k for k, v in DIRS.items()}
    p = best[1]
    return [names[(b[0] - a[0], b[1] - a[1])] for a, b in zip(p, p[1:]) if (b[0] - a[0], b[1] - a[1]) in names]
