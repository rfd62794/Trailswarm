"""grass_pace: once ON the training grass, keep walking INSIDE it instead of handing the step to frontier.

2026-11-13 A/B (slice 2): the Route 24 SHAKE lines still clustered at (4-5,16-17). train_route.step answered None the moment the
agent stood on a grass tile, so frontier (memory-guided, "seek") picked every press from the whole map; it steps out of the
patch onto the plain tile beside it and back in, an edge pace where most presses are not on grass and no encounter rolls
(an encounter needs a step ONTO a grass tile). The shake exemption needs a battle inside the window, so it never applied.

This returns the next press that stays on a known grass tile: straight on while the next tile is grass, else turn round, else
any grass neighbour. Grass comes from the ROM grid when one exists (every tall-grass tile), else from the map's learned
``encounters`` plus the patch (encounter-proven tiles only). No grass neighbour -> None (frontier, as before).
"""
from __future__ import annotations

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
FLIP = {"LEFT": "RIGHT", "RIGHT": "LEFT", "UP": "DOWN", "DOWN": "UP"}
_grids = False   # lazy legs.grid.rom_grids(): False = not tried, None = no ROM


def rom_grass(map_id: int) -> set | None:
    """Every walkable tall-grass tile of the map from the ROM, or None without a ROM / for an undecodable map."""
    global _grids
    if _grids is False:
        from pokeagent.legs.grid import rom_grids
        _grids = rom_grids()
    g = _grids(map_id) if _grids else None
    if g is None:
        return None
    ys, xs = (g.grass & g.walk).nonzero()
    return set(zip(xs.tolist(), ys.tolist())) or None


def tiles_of(src) -> set:
    """{(x, y)} from "x,y" keys or [x, y] pairs (a patch arrives from JSON as lists)."""
    out = set()
    for t in src or ():
        a, b = (t.split(",")[:2] if isinstance(t, str) else t[:2])
        out.add((int(a), int(b)))
    return out


def next_button(grass: set, pos: tuple, heading: str | None, blocked=frozenset()) -> str | None:
    """The press that keeps ``pos`` on grass, or None (not on grass / no grass neighbour). ``blocked``: (x, y) tiles to avoid."""
    if pos not in grass:
        return None
    heading = heading if heading in DIRS else "RIGHT"
    for h in (heading, FLIP[heading], *(d for d in DIRS if d not in (heading, FLIP[heading]))):
        t = (pos[0] + DIRS[h][0], pos[1] + DIRS[h][1])
        if t in grass and t not in blocked:
            return h
    return None


def step(map_id: int, pos: tuple, learned, patch=None, heading: str | None = None, blocked=frozenset()) -> tuple[str, str] | None:
    """(button, why) pacing the grass of ``map_id`` from ``pos`` = (x, y), or None. ``learned``: the map's encounter keys."""
    grass = rom_grass(map_id) or (tiles_of(learned) | tiles_of(patch))
    b = next_button(grass, pos, heading, frozenset(blocked))
    return (b, f"goal team_ready: pacing inside the grass at {pos} (never the edge)") if b else None
