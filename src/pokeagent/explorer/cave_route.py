"""cave_route: lead the cave walk toward the next ladder, using the warps the ROM's map header lists.

Mt Moon's floors are a maze the learned graph only knows where we have walked. The header (pokeagent.atlas.rom_maps) says
where every ladder is, so the agent can walk to the KNOWN tile closest to the stage's ladder and let frontier exploration
take it from there, instead of wandering the least-visited tiles for thousands of presses. A tile already stood on
``MAX_PULL_VISITS`` times no longer pulls (a dead end must not trap the agent in a pull/explore loop).
"""
from __future__ import annotations

from pokeagent.explorer.world import WorldGraph

MAX_PULL_VISITS = 3
MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F, ROUTE4 = 0x3B, 0x3C, 0x3D, 0x0F
# (stage, current floor) -> the map the warp we want leads to. The way out is B2F -> B1F -> its east exit (27,3) to Route 4
# (ROM header: B1F has the only other warp to the outside than 1F's west mouth). ``ctx.ladders`` is built by
# pokeagent.atlas.ladders.rom_ladders (the explorer package may not import the atlas).
LADDER_DEST = {("to_mt_moon", MT_MOON_1F): MT_MOON_B1F, ("mt_moon_b1f", MT_MOON_1F): MT_MOON_B1F,
               ("mt_moon_b2f", MT_MOON_B1F): MT_MOON_B2F, ("through_mt_moon", MT_MOON_B1F): ROUTE4,
               ("through_mt_moon", MT_MOON_B2F): MT_MOON_B1F, ("through_mt_moon", MT_MOON_1F): MT_MOON_B1F}

# The way out of Mt Moon, from the swarm's through_mt_moon run (2026-11-06, 2228 steps): B2F ladder (5,7) -> B1F (23,3), then B1F (27,3).
# B1F is split into regions; of B2F's four ladders only that one lands beside the exit, so through_mt_moon on B2F wants the ladder
# whose landing is nearest the B1F exit tile.
EXIT_NEAR = {("through_mt_moon", MT_MOON_B2F): (27, 3)}


# stage -> (floor to be on, how to reach it): a warp tile of the floor we stand on leading to it, or the exit tile itself.
EXIT_B1F = (MT_MOON_B1F, 27, 3)   # the east mouth: B1F's warp to the outside (ROM header)
STAGE_GOAL = {"to_mt_moon": MT_MOON_B1F, "mt_moon_b1f": MT_MOON_B1F, "mt_moon_b2f": MT_MOON_B2F}


def rom_route_step(maps: dict, stage: str, pos: tuple, cave_plan, blocked_now=()) -> tuple[str, str] | None:
    """The first button of the ROM route (all floors, ladders included) to this stage's goal: the exit mouth for
    through_mt_moon, else a warp to the floor the stage names. None when no plan is wired, no route exists, or we stand on
    the goal floor already."""
    if cave_plan is None or pos[0] not in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F):
        return None
    if stage == "through_mt_moon":
        goals = {EXIT_B1F}
    elif stage in STAGE_GOAL and pos[0] != STAGE_GOAL[stage]:
        goals = set().union(*(cave_plan.warp_tiles(m, STAGE_GOAL[stage]) for m in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F)
                              if m != STAGE_GOAL[stage]))
    else:
        return None
    walls = {m: set(maps.get(str(m), {}).get("blocked", [])) for m in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F)}
    temp: dict = {}
    for m, x, y in blocked_now:
        temp.setdefault(m, set()).add((x, y))
    path = cave_plan(pos, goals, walls, temp)
    if not path:
        return None
    return path[0], f"goal {stage}: ROM route, {len(path)} steps across floors"


def ladder_step(g: WorldGraph, maps: dict, stage: str, pos: tuple, ladders=None) -> tuple[str, str] | None:
    """The next press toward the known tile nearest the stage's ladder; None when there is nothing to gain (already
    there, no ladder wanted on this floor, or the closest tile was tried ``MAX_PULL_VISITS`` times)."""
    dest = LADDER_DEST.get((stage, pos[0]))
    near = EXIT_NEAR.get((stage, pos[0]))
    targets = (ladders(pos[0], dest, near) if near else ladders(pos[0], dest)) if ladders is not None and dest is not None else []
    if not targets:
        return None
    visited = maps.get(str(pos[0]), {}).get("visited", {})

    def gap(t: tuple) -> int:
        return min(abs(t[0] - tx) + abs(t[1] - ty) for tx, ty in targets)

    here = gap((pos[1], pos[2]))
    cands = []
    for key, n in visited.items():
        x, y = (int(v) for v in key.split(","))
        if gap((x, y)) < here and n < MAX_PULL_VISITS:
            cands.append((gap((x, y)), x, y))
    for _d, x, y in sorted(cands)[:6]:  # each try is a BFS
        p = g.path(pos, lambda n, x=x, y=y: n == (pos[0], x, y))
        if p:
            return p[0], f"goal {stage}: {len(p)} steps toward the ROM ladder to 0x{dest:02X} (known tile ({x},{y}))"
    return None
