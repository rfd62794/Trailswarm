"""cerulean_south: the ROM route from Cerulean City to Route 5, which needs no Cut.

ROM-verified (2026-11-15): the south part of Cerulean (rows 29-35, the connection to Route 5, map 0x10) is cut off from the town by the
wall at row 28, whose only gaps are a dead-end alcove (16-17, 28) and a Cut tree (19, 28). It is reached from the back yard of the
burgled house (0x3E): in by the front door (27, 11), across the room to the hole in its back wall (3, 0), out at (27, 9), then east
and south. Exploration never found it (4000 steps patrolling Cerulean), and the learned (16-17, 28) 'walls' are real."""
from __future__ import annotations

from pokeagent.atlas.walkgrid import rom_cave_planner

CERULEAN, HOUSE = 0x03, 0x3E
HOLE = (HOUSE, 3, 0)               # the hole's warp tile in the house's top wall
BOTTOM_ROW = 35                    # Cerulean's last cell row; Route 5's connection spans x 10..29
BOTTOM = {(CERULEAN, x, BOTTOM_ROW) for x in range(10, 30)}
_plan = False                      # lazy: False = not built, None = no ROM


def _planner():
    global _plan
    if _plan is False:
        _plan = rom_cave_planner(maps=frozenset({CERULEAN, HOUSE}))
    return _plan


def route_step(pos: tuple) -> tuple[str, str] | None:
    """(button, why) along the ROM route toward Route 5 from a (map, x, y) in Cerulean or the burgled house, else None."""
    plan = _planner()
    if plan is None or pos[0] not in (CERULEAN, HOUSE):
        return None
    if pos[0] == CERULEAN and pos[2] == BOTTOM_ROW and (CERULEAN, pos[1], pos[2]) in BOTTOM:
        return "DOWN", "goal to_route5: on Cerulean's south edge, pushing DOWN onto Route 5"
    goals = BOTTOM if pos[0] == CERULEAN else {HOLE}
    path = plan(pos, goals)
    if not path and pos[0] == CERULEAN:
        path, goals = plan(pos, {HOLE}), {HOLE}  # the town side: through the burgled house to its hole
    if not path:
        return None
    where = "Route 5 over the ROM route" if goals is BOTTOM else "the burgled house's hole (the way round the wall, no Cut)"
    return path[0], f"goal to_route5: {len(path)} steps toward {where}"
