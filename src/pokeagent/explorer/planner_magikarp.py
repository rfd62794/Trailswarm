"""The buy_magikarp stage: walk to the Mt Moon Pokemon Center (0x44), find the salesman, face him, talk.

He wanders along one row, so his tile is read live from the sprite table every step (goals["_sprites"]: (pic, x, y)).
Which sprite he is comes from the learned NPC memory (the one whose dialog named MAGIKARP, else any wanderer); with
nothing learned yet this returns None and exploration talks to every NPC, as it always did.
"""
from __future__ import annotations

from pokeagent.explorer.world import DIRS, WorldGraph
from pokeagent.magikarp import MT_MOON_CENTER

ROUTE4 = 0x0F
DOOR = (ROUTE4, 11, 6)  # ROM-verified: UP from Route 4 (11,6) enters the Mt Moon Pokemon Center at (3,7)


def salesman_pics(maps: dict) -> set:
    """Sprite picture ids of the Magikarp salesman: dialog naming MAGIKARP first, else the wanderers."""
    npcs = maps.get(str(MT_MOON_CENTER), {}).get("npcs", {}).values()
    named = {e["pic"] for e in npcs if "MAGIKARP" in ((e.get("results") or {}).get("text", "") + e.get("text", "")).upper()}
    return named or {e["pic"] for e in npcs if e.get("moves") and not e.get("trainer")}


def magikarp_step(g: WorldGraph, maps: dict, goals: dict, pos: tuple, facing: str) -> tuple[str, str] | None:
    if pos[0] != MT_MOON_CENTER:
        p = g.path(pos, lambda n: n[0] == MT_MOON_CENTER)
        if p:
            return p[0], f"goal buy_magikarp: {len(p)} steps to the Mt Moon Pokemon Center"
        if pos == DOOR:
            return "UP", "goal buy_magikarp: at the Mt Moon Pokemon Center door, stepping UP"
        if pos[0] == ROUTE4:
            p = g.path(pos, lambda n: n == DOOR)
            if p:
                return p[0], f"goal buy_magikarp: {len(p)} steps to the Pokemon Center door at (11,6)"
        return None  # Route 4's west end is not mapped yet: exploration finds it
    pics = salesman_pics(maps)
    seen = [(x, y) for pic, x, y in goals.get("_sprites", ()) if pic in pics]
    best = None
    for sx, sy in seen:
        for name, (dx, dy) in DIRS.items():
            stand = (MT_MOON_CENTER, sx - dx, sy - dy)  # stand here, face `name`, and he is in front
            if pos == stand:
                return ("A" if facing == name else name), f"goal buy_magikarp: at the salesman ({sx},{sy}), {'talking' if facing == name else 'facing him'}"
            p = g.path(pos, lambda n, s=stand: n == s)
            if p and (best is None or len(p) < len(best[0])):
                best = (p, (sx, sy))
    if best:
        return best[0][0], f"goal buy_magikarp: {len(best[0])} steps to the salesman at {best[1]}"
    return None  # not found / unreachable: exploration talks to the NPCs
