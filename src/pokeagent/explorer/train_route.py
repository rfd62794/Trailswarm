"""Where the gyarados stage trains: Route 24's grass, the same ground the Misty stage grinds on.

The planner has no target for the "gyarados" goal (it is a training stage, not a place), so with the gate live the run fell
through to frontier, whose grass seeking is local: runs that left Route 24 for Cerulean City wandered 31 tiles for 600+
presses, found no grass and were stalled (2026-11-07 swarm-day34). This walks back to Route 24 and then returns None, so
frontier roams its grass.
"""
from __future__ import annotations

from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.explorer.world import WorldGraph

MIN_HP_FRACTION = 0.5  # weaker than this the heal behaviours decide where to go


def step(maps: dict, pos: tuple, blocked, hp: int, mx: int) -> tuple[str, str] | None:
    """The next button toward Route 24, or None (already there / no learned way / too hurt)."""
    if pos[0] == ROUTE24 or not mx or hp / mx < MIN_HP_FRACTION:
        return None
    g = WorldGraph(maps)
    g.blocked_now = frozenset(blocked)
    p = g.path(pos, lambda n: n[0] == ROUTE24)
    return (p[0], f"goal gyarados: {len(p)} steps back to Route 24 to train the trainee") if p else None
