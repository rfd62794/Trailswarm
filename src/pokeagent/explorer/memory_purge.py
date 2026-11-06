"""Heal false walls: a 'blocked' edge whose target tile has been seen holding a wandering NPC was a person, not a wall."""
from __future__ import annotations

from pokeagent.explorer.perceive import DIRS


def npc_tiles(map_data: dict) -> set[tuple[int, int]]:
    """Tiles any wandering NPC (moves=true) was ever seen standing on."""
    out = set()
    for e in map_data.get("npcs", {}).values():
        if e.get("moves"):
            for k in e.get("positions", {}):
                x, y = k.split(",")
                out.add((int(x), int(y)))
    return out


def purge_npc_walls(data: dict) -> int:
    """Drop 'blocked' entries (and their fail counters) whose target tile a wanderer has stood on. Returns how many."""
    removed = 0
    for d in data.get("maps", {}).values():
        tiles = npc_tiles(d)
        if not tiles:
            continue
        keep = []
        for key in d.get("blocked", []):
            try:
                x, y, name = key.split(",")
                dx, dy = DIRS[name]
                hit = (int(x) + dx, int(y) + dy) in tiles
            except (ValueError, KeyError):
                hit = False
            if hit:
                removed += 1
                d.get("fails", {}).pop(key, None)
            else:
                keep.append(key)
        d["blocked"] = keep
    return removed
