"""The road east of Pewter: Route 3, Route 4, Mt Moon, Cerulean City, Misty, Route 24/25, Bill (goals.GOALS from to_route3 on).

Every step walks the LEARNED world graph toward the map of the next unmet goal; when that map is not mapped yet it either
pushes to a map edge (outdoor connections) or returns None so exploration runs. Mt Moon's floors are a ladder maze: they are
left to exploration plus learned warps, never scripted. Map ids are ROM-verified (docs/KNOWLEDGE.md).
"""
from __future__ import annotations

from pokeagent.explorer.cave_route import ladder_step, rom_route_step
from pokeagent.explorer.planner_checkpoint import checkpoint_step
from pokeagent.explorer.planner_magikarp import magikarp_step
from pokeagent.explorer.ship_gate import ship_gate_step
from pokeagent.explorer.world import DUNGEON_MAPS, POKECENTER_MAPS, WorldGraph
from pokeagent.goals import GOALS

PEWTER, ROUTE3, ROUTE4, CERULEAN, ROUTE24 = 0x02, 0x0E, 0x0F, 0x03, 0x23
ROUTE25 = 0x24
CERULEAN_GYM = 0x41
SS_ANNE_BOW = 0x63  # 2F stairs (2,11) -> 3F deck (0x61) -> LEFT -> bow; the captain's cabin is reached from there
OUTDOORS = (PEWTER, ROUTE3, ROUTE4, CERULEAN, ROUTE24, 0x24)
CAVE = tuple(sorted(DUNGEON_MAPS))
EXIT_X = 24  # Route 4 tile x of the cave-exit warp; the west part (Pokecenter 11, entrance 18) is left of it

TRAIN_OUTSIDE_STAGES = ("to_route4", "buy_magikarp", "to_mt_moon", "mt_moon_b1f", "mt_moon_b2f", "through_mt_moon")  # the Mt Moon stage trains on Route 3
LADDER = tuple(GOALS[GOALS.index("to_route3"):])


def _on(m: int):
    return lambda n: n[0] == m


# stage -> node predicate for "I have arrived" (None: no place to walk to, exploration handles it)
TARGETS = {"to_route3": _on(0x0E), "to_route4": _on(ROUTE4), "buy_magikarp": _on(0x44), "to_mt_moon": _on(0x3B), "mt_moon_b1f": _on(0x3C),
           "mt_moon_b2f": _on(0x3D), "through_mt_moon": lambda n: n[0] == ROUTE4 and n[1] >= EXIT_X,
           "to_cerulean": _on(CERULEAN), "heal_cerulean": _on(0x40), "beat_misty": _on(CERULEAN_GYM),
           "nugget_bridge": _on(ROUTE24), "to_bill": _on(0x58), "ss_ticket": None,
           # S.S. Anne (2026-11-06): the rival fight at the east end of 2F is not on the way and a lone starter loses it;
           # walk the learned warps 2F -> 3F -> bow instead of letting the frontier run east into him
           "rival_ss_anne": _on(SS_ANNE_BOW), "ss_anne_captain": _on(SS_ANNE_BOW)}


def _edge_frontier(g: WorldGraph, maps: dict, pos: tuple, stage: str, side: str, occupied: frozenset = frozenset()) -> tuple[str, str] | None:
    """Push toward a map edge ('RIGHT' = east, 'UP' = north): the extreme visited tile whose `side` is still unknown.
    `occupied` = (x, y) of people standing on the map: a tile whose `side` neighbour holds one only LOOKS unexplored
    (a person is never learned as a wall), and pushing into him loops forever (Nugget Bridge trainers, 2026-11-06)."""
    d = maps.get(str(pos[0]), {})
    visited, blocked = d.get("visited", {}), set(d.get("blocked", []))
    dx, dy = {"RIGHT": (1, 0), "UP": (0, -1)}[side]
    tiles = [tuple(map(int, k.split(","))) for k in visited]
    tiles = [t for t in tiles if f"{t[0]},{t[1]},{side}" not in blocked and f"{t[0] + dx},{t[1] + dy}" not in visited
             and f"{t[0]},{t[1]},{side}" not in d.get("jumps", {}) and f"{t[0]},{t[1]},{side}" not in d.get("warps", {})
             and (t[0] + dx, t[1] + dy) not in occupied]
    order = (lambda t: (-t[0], abs(t[1] - pos[2]))) if side == "RIGHT" else (lambda t: (t[1], abs(t[0] - pos[1])))
    word = "easternmost" if side == "RIGHT" else "northernmost"
    for tx, ty in sorted(tiles, key=order)[:8]:  # each try is a BFS
        if (pos[1], pos[2]) == (tx, ty):
            return side, f"goal {stage}: at the {word} open tile, pushing {side} for the map edge"
        p = g.path(pos, lambda n, tx=tx, ty=ty: n == (pos[0], tx, ty))
        if p:
            return p[0], f"goal {stage}: {len(p)} steps to the {word} known tile ({tx},{ty})"
    return None


def _back_to(g: WorldGraph, pos: tuple, stage: str, m: int, what: str) -> tuple[str, str] | None:
    p = g.path(pos, _on(m))
    return (p[0], f"goal {stage}: {len(p)} steps back to {what}") if p else None


def _misty_step(g: WorldGraph, goals: dict, pos: tuple) -> tuple[str, str] | None:
    """Gym at the training level, else train: Route 24 grass and its trainers (the Route 1 branch is far behind us)."""
    level, need = goals.get("_level", 0), goals.get("_train_level", 8)
    if level == 0 or level >= need:
        if pos[0] == CERULEAN_GYM:
            return None  # Misty and the gym trainers: battle and dialog behaviours, exploration for the way in
        return _back_to(g, pos, "beat_misty", CERULEAN, "Cerulean City") if pos[0] != CERULEAN else None
    if pos[0] != ROUTE24:
        return _back_to(g, pos, "beat_misty", ROUTE24, f"Route 24 to train to L{need} (now L{level})")
    return None  # on Route 24: roam the grass


def east_road_step(g: WorldGraph, maps: dict, goals: dict, pos: tuple, facing: str = "UP") -> tuple[str, str] | None:
    stage = next((s for s in LADDER if not goals.get(s)), None)
    ckpt = checkpoint_step(g, goals, pos, facing)  # new town: move the respawn point forward before pushing on
    if ckpt:
        return ckpt
    gate = ship_gate_step(g, goals, stage, pos, goals.get("_grid_get"))  # ready before boarding; the way back to Vermilion after a blackout
    if gate:
        return gate
    target = TARGETS.get(stage)
    if stage is None or target is None:
        return None
    if stage == "buy_magikarp" and (pos[0] == 0x44 or pos[0] not in POKECENTER_MAPS):
        step = magikarp_step(g, maps, goals, pos, facing)  # None: not mapped / salesman not found - fall through
        if step:
            return step
    if pos[0] in POKECENTER_MAPS:
        if stage == "heal_cerulean" and pos[0] == 0x40:  # the goal IS the nurse: walk up the door column and talk to her
            if pos[1] != 3:
                return ("RIGHT" if pos[1] < 3 else "LEFT"), f"goal {stage}: crossing the Pokecenter to the counter"
            if pos[2] > 2:
                return "UP", f"goal {stage}: walking up to the nurse"
            return ("A" if facing == "UP" else "UP"), f"goal {stage}: at the nurse, {'talking' if facing == 'UP' else 'facing her'} to heal"
        if goals.get("_center_intent"):
            return None  # a deliberate stop (heal, PC, a purchase): leave the center to the behaviour that set the intent
        # the center is a stop, not a goal: 2,048 of 6,000 presses went to its salesman (2026-11-05)
        p = g.path(pos, lambda n: n[0] in OUTDOORS)
        if p:
            return p[0], f"goal {stage}: leaving the Pokecenter ({len(p)} steps)"
        if pos[1] != 3:
            return ("RIGHT" if pos[1] < 3 else "LEFT"), f"goal {stage}: crossing the Pokecenter to its door column"
        return "DOWN", f"goal {stage}: walking out of the Pokecenter by its door"
    hp, mx = goals.get("_hp", (0, 0))
    need, level = goals.get("_train_level", 8), goals.get("_level", 0)
    if stage in TRAIN_OUTSIDE_STAGES and pos[0] not in CAVE and 0 < level < need and mx and hp / mx >= 0.5:
        # too weak for the cave (and Route 4's trainers): grind Route 3 first
        return None if pos[0] == ROUTE3 else _back_to(g, pos, stage, ROUTE3, f"Route 3 to train to L{need} (now L{level})")
    if pos[0] in CAVE:  # the whole dungeon is in the ROM: route across floors first, learned walls only delay it
        rom = rom_route_step(maps, stage, pos, goals.get("_cave_plan"), goals.get("_blocked_now", ()),
                              goals.get("_rom_route"))
        if rom:
            return rom
    training = stage == "beat_misty" and 0 < goals.get("_level", 0) < goals.get("_train_level", 8)
    if not training:
        p = g.path(pos, target)
        if p:
            return p[0], f"goal {stage}: {len(p)} steps toward it over the learned world"
    if pos[0] in CAVE and stage in ("to_mt_moon", "mt_moon_b1f", "mt_moon_b2f", "through_mt_moon"):
        lead = ladder_step(g, maps, stage, pos, goals.get("_ladders"))  # the ROM header's ladder, via the learned tile closest to it
        if lead:
            return lead
    if stage == "beat_misty":
        return _misty_step(g, goals, pos)
    if stage == "through_mt_moon" and pos[0] not in CAVE:  # out on Route 3/4 again: back in, the exit is inside
        return (_back_to(g, pos, stage, 0x3C, "Mt Moon B1F, where the exit is") or _back_to(g, pos, stage, 0x3B, "Mt Moon 1F"))
    push = {"to_route3": (PEWTER, "RIGHT", "Pewter City"), "to_route4": (ROUTE3, "UP", "Route 3"),
            "to_cerulean": (ROUTE4, "RIGHT", "Route 4"), "nugget_bridge": (CERULEAN, "UP", "Cerulean City"),
            "to_bill": (ROUTE24, "RIGHT", "Route 24")}.get(stage)
    if push is None:
        return None  # Mt Moon floors, the Pokecenter door, Bill's house: exploration + learned warps
    home, side, name = push
    if stage == "to_bill":
        if pos[0] == ROUTE25:
            return None  # Bill's house is the only warp on Route 25: exploration finds it (walking back to Route 24 would undo the arrival)
        east = g.path(pos, _on(ROUTE25)) if pos[0] == home else None
        if east:  # Route 24's east connection is already learned: walk to it rather than hunting a frontier
            return east[0], f"goal {stage}: {len(east)} steps to Route 25 over the learned world"
    occupied = frozenset((sx, sy) for _pic, sx, sy in goals.get("_sprites", ()))
    return _edge_frontier(g, maps, pos, stage, side, occupied) if pos[0] == home else _back_to(g, pos, stage, home, name)
