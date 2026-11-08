"""Where the team_ready stage trains - and where a grind episode walks to.

The planner has no target for the "team_ready" goal (it is a training stage, not a place), so with the gate live the run fell
through to frontier, whose grass seeking is local: runs that left Route 24 for Cerulean City wandered 31 tiles for 600+
presses, found no grass and were stalled (2026-11-07 swarm-day34). This walks back to the target map and then returns None, so
frontier roams its grass. The target was Route 24 only; a grind episode (explorer.grind_episode) generalises it to any
point's map and patch.
"""
from __future__ import annotations

from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.explorer.world import WorldGraph

CERULEAN = 0x03       # Route 24's south exit
MIN_HP_FRACTION = 0.5  # weaker than this the heal behaviours decide where to go


class OutsideSet:
    """``avoid_maps`` that contains every map NOT in ``allowed``: an active grind episode pins the
    agent to the point's map plus its Pokecenter map (the Nugget Bridge 3<->35 ping-pong fix)."""

    def __init__(self, allowed) -> None:
        self.allowed = frozenset(m for m in allowed if m is not None)

    def __contains__(self, m) -> bool:
        return m not in self.allowed


def step(maps: dict, pos: tuple, blocked, hp: int, mx: int, target: int = ROUTE24, patch=None) -> tuple[str, str] | None:
    """The next button toward the target map's grass, or None (on it / no learned way / too hurt).

    Off the target the goal is the map itself; on it, the nearest patch tile (encounter-proven grass, or
    the map's learned ``encounters`` when no patch is given), so a run that has seen every tile does not
    shuffle at the south end (steps 300-1800 of the 2026-11-07 repro)."""
    if not mx or hp / mx < MIN_HP_FRACTION:
        return None
    grass = set(patch) if patch is not None else set((maps.get(str(target)) or {}).get("encounters", {}))
    grass = {f"{t[0]},{t[1]}" if not isinstance(t, str) else t for t in grass}
    what = "Route 24" if target == ROUTE24 else f"map 0x{target:02X}"
    if pos[0] == target:
        if not grass or f"{pos[1]},{pos[2]}" in grass:
            return None
        goal = (lambda n: n[0] == target and f"{n[1]},{n[2]}" in grass)
    else:
        goal = (lambda n: n[0] == target)
    g = WorldGraph(maps)
    g.blocked_now = frozenset(blocked)
    p = g.path(pos, goal)
    return (p[0], f"goal team_ready: {len(p)} steps to {what}'s grass to train the trainee") if p else None


def stay_on_route(map_id: int, training_live: bool, episode=None) -> set | None:
    """Maps frontier must not walk into. While training on Route 24: Cerulean (with every Route 24 tile already seen, the
    least-visited exit is the Cerulean connection, and step() then sends it straight back - Route 24 <-> Cerulean, 1,200
    steps, 2026-11-07). While a grind episode runs: everything outside the episode's map set (its point plus its
    Pokecenter), so no behaviour can ping-pong across a map edge mid-grind."""
    if episode is not None:
        return OutsideSet(episode.get("maps") or ())
    return {CERULEAN} if training_live and map_id == ROUTE24 else None
