"""Where the gyarados stage trains: Route 24's grass, the same ground the Misty stage grinds on.

The planner has no target for the "gyarados" goal (it is a training stage, not a place), so with the gate live the run fell
through to frontier, whose grass seeking is local: runs that left Route 24 for Cerulean City wandered 31 tiles for 600+
presses, found no grass and were stalled (2026-11-07 swarm-day34). This walks back to Route 24 and then returns None, so
frontier roams its grass.
"""
from __future__ import annotations

from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.explorer.world import WorldGraph

CERULEAN = 0x03       # Route 24's south exit
MIN_HP_FRACTION = 0.5  # weaker than this the heal behaviours decide where to go


def step(maps: dict, pos: tuple, blocked, hp: int, mx: int) -> tuple[str, str] | None:
    """The next button toward Route 24's grass, or None (standing on grass / no learned way / too hurt).

    Off Route 24 the target is the map itself; on it, the nearest tile where a wild encounter has happened, so a run that has
    seen every tile does not shuffle at the south end (steps 300-1800 of the 2026-11-07 repro)."""
    if not mx or hp / mx < MIN_HP_FRACTION:
        return None
    grass = set((maps.get(str(ROUTE24)) or {}).get("encounters", {}))
    if pos[0] == ROUTE24:
        if not grass or f"{pos[1]},{pos[2]}" in grass:
            return None
        goal, what = (lambda n: n[0] == ROUTE24 and f"{n[1]},{n[2]}" in grass), "to Route 24's grass"
    else:
        goal, what = (lambda n: n[0] == ROUTE24), "back to Route 24"
    g = WorldGraph(maps)
    g.blocked_now = frozenset(blocked)
    p = g.path(pos, goal)
    return (p[0], f"goal gyarados: {len(p)} steps {what} to train the trainee") if p else None

def stay_on_route(map_id: int, training_live: bool) -> set | None:
    """Maps frontier must not walk into while it roams Route 24 for the trainee: with every Route 24 tile already seen, the
    least-visited exit is the Cerulean connection, and step() then sends it straight back (Route 24 <-> Cerulean, 1,200 steps, 2026-11-07)."""
    return {CERULEAN} if training_live and map_id == ROUTE24 else None
