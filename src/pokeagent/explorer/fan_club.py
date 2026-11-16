"""fan_club: Vermilion's Pokemon Fan Club (the Bike Voucher) and the trip back to Cerulean's Bike Shop (stages pokemon_fan_club, bike_voucher, bike_shop, bicycle).

Live marathon-2026-11-16a: after Cut was taught the stage pokemon_fan_club had no TARGETS entry, so no planner step, no patrol_exit
(it needs a target on another map) and no GoalTalk: the explorer wandered into the Old Rod house (0xA3) and patrolled it for 8,000 steps.
ROM-verified: the Fan Club (0x5A) door is Vermilion's warp (9,13); its chairman gives the Bike Voucher (bag item 45) after a talk
with YES to hear his story (the dialog behaviours answer YES). The Bike Shop (0x42) door is Cerulean's warp (13,25); the clerk swaps the voucher
for the Bicycle (bag item 6). The way back is the reverse of route5_vermilion: Vermilion's north edge onto Route 6, the Route 6 house, the
Underground Path, the Route 5 house, Route 5's north edge into Cerulean's south part and, through the burgled house (cerulean_south), up to the town.
The planner is the injected ctx.route_plan over PLANNER_MAPS; explorer never imports atlas."""
from __future__ import annotations

from pokeagent.explorer import cerulean_south, route5_vermilion as r5v

VERMILION, FAN_CLUB, BIKE_SHOP, CERULEAN = 0x05, 0x5A, 0x42, 0x03
MAPS = frozenset({VERMILION, FAN_CLUB})
PLANNER_MAPS = cerulean_south.MAPS | r5v.MAPS | MAPS  # what ctx.route_plan is built over (the demo and the headless tool both use it)
FAN_STAGES = ("pokemon_fan_club", "bike_voucher")
BIKE_STAGES = ("bike_shop", "bicycle")
GYM_STAGE = "vermilion_gym_entry"  # after the Bicycle: back to Vermilion and its gym door (a Cut tree stands in front: no Cut-use behaviour yet)
STAGES = FAN_STAGES + BIKE_STAGES + (GYM_STAGE,)
GYM = 0x5C
GYM_DOOR = (VERMILION, 12, 19)                         # Vermilion's warp into the gym
FAN_DOOR = (VERMILION, 9, 13)                          # Vermilion's warp into the Fan Club
FAN_EXIT = {(FAN_CLUB, 2, 7), (FAN_CLUB, 3, 7)}        # the Fan Club's door mat: a bottom-edge warp, fired by a press DOWN
# Vermilion row 0 -> Route 6 row 35 (x - 10): the cells walkable on both sides AND joined to the rest of Route 6 (ROM grids: Route 6's
# row 35 x 11-19 is a pocket the house cannot be reached from, so only x 8-9 = Vermilion 18-19 are the way north)
VERMILION_TOP = {(VERMILION, x, 0) for x in (18, 19)}
HOUSE_5_EXIT = {(r5v.PATH_5, 3, 7), (r5v.PATH_5, 4, 7)}   # the Route 5 house's door mat (press DOWN out onto Route 5)
# Route 5 row 0 -> Cerulean row 35 (x + 10). Route 5's x 6-13 lead into a walled pocket of Cerulean (x 16-23, rows 34-35: ROM walls at x 15 and 24, row 33) that
# the south part cannot be left from (live headless run 2026-11-16: 2,000 steps Route 5 <-> that pocket); x 1-4 and 15-18 are the way to the town side.
ROUTE5_TOP = {(r5v.ROUTE5, x, 0) for x in (1, 2, 3, 4, 15, 16, 17, 18)}
BIKE_DOOR = (CERULEAN, 13, 25)                         # Cerulean's warp into the Bike Shop
HOUSE_MATS = {(cerulean_south.HOUSE, 2, 7), (cerulean_south.HOUSE, 3, 7)}  # the burgled house's front-door mat: the way from its hole pocket (Cerulean's south part) up to the town


def _ask(plan, pos, goals, maps, blocked_now):
    walls = {m: set((maps or {}).get(str(m), {}).get("blocked", ())) for m in PLANNER_MAPS}
    blocks: dict = {}
    for m, x, y in blocked_now:
        blocks.setdefault(m, set()).add((x, y))
    return plan(pos, goals, walls, blocks)


def _toward(plan, pos, goals, maps, blocked_now, why) -> tuple[str, str] | None:
    path = _ask(plan, pos, goals, maps, blocked_now)
    return (path[0], f"goal {why}: {len(path)} steps") if path else None


def _forward(stage, pos, plan, maps, blocked_now):
    """To the Fan Club door in Vermilion; from the Cerulean / Route 5 / Route 6 side, back over route5_vermilion first."""
    if pos in FAN_EXIT:
        return "DOWN", f"goal {stage}: on the Fan Club's door mat, pressing DOWN to leave"
    if pos[0] == FAN_CLUB:
        return _toward(plan, pos, FAN_EXIT, maps, blocked_now, f"{stage}: out of the Fan Club")
    if pos[0] == VERMILION:
        door, what = (GYM_DOOR, "the gym door (12,19)") if stage == GYM_STAGE else (FAN_DOOR, "the Fan Club door (9,13)")
        return _toward(plan, pos, {door}, maps, blocked_now, f"{stage}: to {what}")
    if pos[0] in r5v.MAPS:
        return r5v.route_step(pos, plan, maps, blocked_now)
    return cerulean_south.route_step(pos, plan, maps, blocked_now)


def _back(stage, pos, plan, maps, blocked_now):
    """The reverse of route5_vermilion, then up to the Bike Shop door in Cerulean."""
    why = f"{stage}: back to Cerulean's Bike Shop"
    if pos in FAN_EXIT or pos in HOUSE_5_EXIT or pos in HOUSE_MATS:
        return "DOWN", f"goal {why}: on a door mat, pressing DOWN to leave"
    if pos in VERMILION_TOP or pos in ROUTE5_TOP:
        return "UP", f"goal {why}: on a map's north edge, pushing UP"
    if pos[0] == FAN_CLUB:
        goals = FAN_EXIT
    elif pos[0] == VERMILION:
        goals = VERMILION_TOP
    elif pos[0] == r5v.ROUTE5:
        goals = ROUTE5_TOP
    elif pos[0] in (r5v.ROUTE6, r5v.PATH_6, r5v.PATH_NS, r5v.PATH_5):
        goals = HOUSE_5_EXIT  # one plan from Route 6 through both houses and the path (warps are planned through)
    elif pos[0] == cerulean_south.HOUSE:
        goals = HOUSE_MATS
    elif pos[0] == CERULEAN:  # the town side walks to the shop; the south side (Route 5's end) only reaches the burgled house's hole, so through it
        return _toward(plan, pos, {BIKE_DOOR}, maps, blocked_now, why) or _toward(plan, pos, {(CERULEAN, 27, 9)}, maps, blocked_now, why)
    else:
        return None
    return _toward(plan, pos, goals, maps, blocked_now, why)


def route_step(stage: str, pos: tuple, plan, maps: dict | None = None, blocked_now=()) -> tuple[str, str] | None:
    """(button, why) toward the Fan Club (FAN_STAGES) or the Bike Shop (BIKE_STAGES) from a (map, x, y), else None.
    Inside the target map the stage is a talk (GoalTalk), not a route."""
    if plan is None or stage not in STAGES:
        return None
    if stage in FAN_STAGES:
        return None if pos[0] == FAN_CLUB else _forward(stage, pos, plan, maps, blocked_now)
    if stage == GYM_STAGE:
        return None if pos[0] == GYM else _forward(stage, pos, plan, maps, blocked_now)  # the Bike Shop is left by patrol_exit (its learned door)
    return None if pos[0] == BIKE_SHOP else _back(stage, pos, plan, maps, blocked_now)
