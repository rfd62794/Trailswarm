"""cerulean_south: the ROM route from Cerulean City to Route 5, which needs no Cut.

ROM-verified (2026-11-15): the south part of Cerulean (rows 29-35, the connection to Route 5, map 0x10) is cut off from the town by the
wall at row 28, whose only gaps are a dead-end alcove (16-17, 28) and a Cut tree (19, 28). It is reached from the back yard of the
burgled house (0x3E): in by the front door (27, 11), across the room to the hole in its back wall (3, 0), out at (27, 9), then east
and south. Exploration never found it (4000 steps patrolling Cerulean), and the learned (16-17, 28) 'walls' are real.
The planner (atlas.walkgrid.rom_cave_planner over MAPS) is injected through ctx.route_plan -> goals["_route_plan"]: explorer never imports atlas."""
from __future__ import annotations

CERULEAN, HOUSE = 0x03, 0x3E
MAPS = frozenset({CERULEAN, HOUSE})
HOLE = (HOUSE, 3, 0)               # the hole's warp tile in the house's top wall
BOTTOM_ROW = 35                    # Cerulean's last cell row; Route 5's connection spans x 10..29 (the good part: BOTTOM)
# Only x 11-14 and 25-28 lead onto Route 5's open corridors (its x 1-4 / 15-18). Cerulean x 16-23 (joined to the south part) opens onto Route 5's sealed middle (x 6-13,
# ROM: closed rooms whose only way out is back up): pressing DOWN there trapped the explorer (fresh-memory headless run 2026-11-16, 2,000 steps).
BOTTOM = {(CERULEAN, x, BOTTOM_ROW) for x in (*range(11, 15), *range(25, 29))}


def route_step(pos: tuple, plan, maps: dict | None = None, blocked_now=()) -> tuple[str, str] | None:
    """(button, why) along the ROM route toward Route 5 from a (map, x, y) in Cerulean or the burgled house, else None.
    ``plan`` is the injected planner (None: no ROM). Learned walls and temporarily blocked tiles are passed to it; the planner
    drops them itself when they would cut the ROM route off, so they delay it but never remove it."""
    if plan is None or pos[0] not in MAPS:
        return None
    if pos[0] == CERULEAN and pos[2] == BOTTOM_ROW and (CERULEAN, pos[1], pos[2]) in BOTTOM:
        return "DOWN", "goal to_route5: on Cerulean's south edge, pushing DOWN onto Route 5"
    walls = {m: set((maps or {}).get(str(m), {}).get("blocked", ())) for m in MAPS}
    blocks: dict = {}
    for m, x, y in blocked_now:
        blocks.setdefault(m, set()).add((x, y))
    def go(goals):
        return plan(pos, goals, walls, blocks)
    path, goals = (go(BOTTOM), BOTTOM) if pos[0] == CERULEAN else (None, {HOLE})
    if not path:
        path, goals = go({HOLE}), {HOLE}  # the town side (or the house): through the burgled house to its hole
    if not path:
        return None
    where = "Route 5 over the ROM route" if goals is BOTTOM else "the burgled house's hole (the way round the wall, no Cut)"
    return path[0], f"goal to_route5: {len(path)} steps toward {where}"
