"""cave_route: lead the cave walk toward the next ladder, using the warps the ROM's map header lists.

Mt Moon's floors are a maze the learned graph only knows where we have walked. The header (pokeagent.atlas.rom_maps) says
where every ladder is, so the agent can walk to the KNOWN tile closest to the stage's ladder and let frontier exploration
take it from there, instead of wandering the least-visited tiles for thousands of presses. A tile already stood on
``MAX_PULL_VISITS`` times no longer pulls (a dead end must not trap the agent in a pull/explore loop).
"""
from __future__ import annotations

from pokeagent.explorer.world import DIRS, WorldGraph

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


MAX_BUMPS = 4        # presses in a row from one tile that went nowhere before that edge is held blocked ...
WAIT_CYCLES = 3      # wait episodes for the same next tile before it is hard-walled and the planner routes around it
HARD_WALL_ASKS = 300  # ... for this many planner asks (about steps), or until the floor changes; never persisted


def _route_cache(cache: dict | None) -> dict:
    return cache if cache is not None else {}


def rom_route_step(maps: dict, stage: str, pos: tuple, cave_plan, blocked_now=(), cache: dict | None = None) -> tuple[str, str] | None:
    """The first button of the ROM route (all floors, ladders included) to this stage's goal: the exit mouth for
    through_mt_moon, else a warp to the floor the stage names. None when no plan is wired, no route exists, or we stand on
    the goal floor already. ``cache`` (ctx.rom_route) keeps the planned path: it is re-planned only when we leave it or the
    NPC-block set changes, and an edge that failed MAX_BUMPS presses in a row becomes a hard wall for HARD_WALL_ASKS asks
    (cleared on a floor change, never set under an NPC, never persisted)."""
    if cave_plan is None or pos[0] not in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F):
        return None
    if stage == "through_mt_moon":
        goals = {EXIT_B1F}
    elif stage in STAGE_GOAL and pos[0] != STAGE_GOAL[stage]:
        goals = set().union(*(cave_plan.warp_tiles(m, STAGE_GOAL[stage]) for m in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F)
                              if m != STAGE_GOAL[stage]))
    else:
        return None
    c = _route_cache(cache)
    tick = c["tick"] = c.get("tick", 0) + 1
    edges = c.setdefault("edges", {})            # (floor, "x,y,DIR") -> tick at which the hard wall expires
    if c.get("floor") != pos[0]:
        edges.clear()                            # a floor change clears them: the bump was this floor's
        c["floor"] = pos[0]
    for k in [k for k, until in edges.items() if until <= tick]:
        del edges[k]
    hard: dict = {}
    for (m, e) in edges:
        hard.setdefault(m, set()).add(e)
    last = c.get("last")                      # (pos, button) of the previous answer
    if last and last[0] == pos:               # asked again from the same tile: the press went nowhere (wall, NPC, fight, page)
        c["bumps"] = c.get("bumps", 0) + 1
        if c["bumps"] >= MAX_BUMPS:
            dx, dy = DIRS[last[1]]
            ahead = (pos[0], pos[1] + dx, pos[2] + dy)
            if ahead not in set(blocked_now):    # a person standing there is a wanderer to wait for, not a wall
                edges[(pos[0], f"{pos[1]},{pos[2]},{last[1]}")] = tick + HARD_WALL_ASKS
                hard.setdefault(pos[0], set()).add(f"{pos[1]},{pos[2]},{last[1]}")
            c["bumps"], c["path"] = 0, None
    else:
        c["bumps"] = 0
    temp: dict = {}
    for m, x, y in blocked_now:
        temp.setdefault(m, set()).add((x, y))
    key = (stage, frozenset(blocked_now), tuple(sorted(edges)))
    path = c.get("path")
    if c.get("key") == key and path and pos in path["cells"][:-1]:
        i = path["cells"].index(pos)
        buttons = path["buttons"][i:]
    else:
        walls = {m: set(maps.get(str(m), {}).get("blocked", [])) for m in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F)}
        buttons = cave_plan(pos, goals, walls, temp, hard)
        c["key"] = key
        c["path"] = {"cells": cave_plan.follow(pos, buttons), "buttons": list(buttons)} if buttons else None
    if not buttons:
        c["last"] = None
        return None
    dx, dy = DIRS.get(buttons[0], (0, 0))
    ahead = (pos[0], pos[1] + dx, pos[2] + dy)
    if ahead in set(blocked_now):
        # The only way on runs through a tile a person just stood on (they blocked our last press): wait for them to move
        # instead of bumping again (31 RIGHT presses at Mt Moon 1F (6,23)); the block decays and the press is retried.
        edge = (pos[0], f"{pos[1]},{pos[2]},{buttons[0]}")
        if not c.get("waiting"):                      # a new wait episode (the previous ask was a real press)
            eps = c.setdefault("episodes", {})
            eps[edge] = eps.get(edge, 0) + 1
            if eps[edge] > WAIT_CYCLES:               # a stationary NPC: stop waiting, route around it for the wall's window
                edges[edge] = tick + HARD_WALL_ASKS
                eps.pop(edge, None)
                c["waiting"], c["path"] = False, None
                hard.setdefault(pos[0], set()).add(edge[1])
                buttons = cave_plan(pos, goals, {m: set(maps.get(str(m), {}).get("blocked", [])) for m in (MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F)},
                                    temp, hard)
                if not buttons:
                    c["last"] = None
                    return None
                c["last"] = (pos, buttons[0])
                return buttons[0], f"goal {stage}: ROM route around a person who did not move, {len(buttons)} steps"
        c["last"], c["waiting"] = None, True
        return "", f"goal {stage}: ROM route blocked by a person at the next tile - waiting for them to move"
    c["waiting"] = False
    c["last"] = (pos, buttons[0])
    return buttons[0], f"goal {stage}: ROM route, {len(buttons)} steps across floors"


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
