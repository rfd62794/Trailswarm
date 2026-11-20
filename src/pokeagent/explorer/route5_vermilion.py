"""route5_vermilion: the ROM route from Route 5 to Vermilion City through the Underground Path (stages to_route6, to_vermilion).

ROM-verified (2026-11-15, map headers): Route 5 (0x10) warp (17,27) -> the Route 5 path house (0x47) -> its warp (4,4) -> the Underground Path
(0x77) -> its warp (2,41) -> the Route 6 path house (0x4A) -> out by (3,7)/(4,7) (destination 255: back to the outdoor map you came from, Route 6
0x11) -> Route 6's south edge (row 35, x 8-9 and 11-19) -> Vermilion (0x05). The Saffron gate houses are shut by the thirsty guards; this is
the intended way. Exploration alone oscillated Cerulean/Route 5 (4000-step live run): no stage past to_route5 had a target.
The planner is the injected ctx.route_plan (atlas.walkgrid.rom_cave_planner over cerulean_south.MAPS | MAPS); explorer never imports atlas."""
from __future__ import annotations

ROUTE5, PATH_5, PATH_NS, PATH_6, ROUTE6, VERMILION = 0x10, 0x47, 0x77, 0x4A, 0x11, 0x05
MAPS = frozenset({ROUTE5, PATH_5, PATH_NS, PATH_6, ROUTE6})
STAGES = ("to_route6", "to_vermilion")
EXIT = {(PATH_6, 3, 7), (PATH_6, 4, 7)}              # the Route 6 house's door mat: a bottom-edge warp, fired by a press DOWN
SEALED_TOP = {(ROUTE5, x, 0) for x in range(6, 14)}  # Route 5's middle (x 6-13) is a set of closed rooms joined only to Cerulean's row 35 x 16-23: the way out is back UP
BOTTOM_ROW = 35
BOTTOM = {(ROUTE6, x, BOTTOM_ROW) for x in (8, 9, *range(11, 20))}  # Route 6's walkable cells on the connection to Vermilion


def route_step(pos: tuple, plan, maps: dict | None = None, blocked_now=()) -> tuple[str, str] | None:
    """(button, why) along the ROM route toward Route 6 / Vermilion from a (map, x, y) on Route 5, the path or Route 6, else None."""
    if plan is None or pos[0] not in MAPS:
        return None
    if pos in EXIT:
        return "DOWN", "goal route5-vermilion: on the Route 6 house's door mat, pressing DOWN out onto Route 6"
    if pos in BOTTOM:
        return "DOWN", "goal to_vermilion: on Route 6's south edge, pushing DOWN into Vermilion"
    walls = {m: set((maps or {}).get(str(m), {}).get("blocked", ())) for m in MAPS}
    blocks: dict = {}
    for m, x, y in blocked_now:
        blocks.setdefault(m, set()).add((x, y))
    goals = BOTTOM if pos[0] == ROUTE6 else EXIT  # Route 5 and the path chain to the house door in one plan (warps are planned through)
    path = plan(pos, goals, walls, blocks)
    if not path and pos[0] == ROUTE5:  # no way on from here: inside the sealed middle, back up to Cerulean's south part
        if pos in SEALED_TOP:
            return "UP", "goal route5-vermilion: sealed part of Route 5, back UP to Cerulean"
        path = plan(pos, SEALED_TOP, walls, blocks)
        if path:
            return path[0], f"goal route5-vermilion: {len(path)} steps back up out of Route 5's sealed middle"
    if not path:
        return None
    where = "Vermilion over Route 6" if goals is BOTTOM else "Route 6 through the Underground Path (the gate houses are shut)"
    return path[0], f"goal route5-vermilion: {len(path)} steps toward {where}"
