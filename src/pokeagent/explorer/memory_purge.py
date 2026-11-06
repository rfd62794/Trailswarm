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


def purge_enclosed_walls(data: dict) -> int:
    """Drop the walls of a tile we stood on (``visited``) that memory says is blocked in ALL four directions: nobody walks
    into a tile with no way out, so those were learned while a full-screen page (Pokedex entry) swallowed the presses
    (Mt Moon B2F, 2026-11-05; the stuck_tile anomaly records show learned_blocked = all four). Only learned ``blocked``
    entries and their fail counters go: ROM data, warps and jumps are never touched. Returns how many entries were dropped."""
    removed = 0
    for d in data.get("maps", {}).values():
        blocked = set(d.get("blocked", []))
        enclosed = []
        for key in d.get("visited", {}):
            keys = [f"{key},{name}" for name in DIRS]
            if all(k in blocked for k in keys):
                enclosed += keys
        if enclosed:
            drop = set(enclosed)
            d["blocked"] = [k for k in d["blocked"] if k not in drop]
            for k in enclosed:
                d.get("fails", {}).pop(k, None)
            removed += len(enclosed)
    return removed
