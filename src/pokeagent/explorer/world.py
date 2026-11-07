"""World graph over the learned map memory: BFS across floors and doors (moved from tools/explore_plan.py)."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Callable


DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
STARTERS = ("BULBASAUR", "CHARMANDER", "SQUIRTLE")


def pokecenter_maps(names_path: Path | None = None) -> tuple[int, ...]:
    """Every map whose ROM name ends in POKECENTER (11 of them), from atlas/map_names.json, sorted. The list was hand-typed with
    4 of the 11 before; a missing one meant no nurse planning, no 90% heal threshold and no veto exemption in that town."""
    path = names_path or Path(__file__).resolve().parents[1] / "atlas" / "map_names.json"
    try:
        names = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (41, 58, 0x44, 0x40)  # the four the explorer was written against
    return tuple(sorted(int(k) for k, v in names.items() if str(v).endswith("POKECENTER")))


POKECENTER_MAPS = pokecenter_maps()  # computed once at import: Viridian 41, Pewter 58, Cerulean 0x40, Mt Moon 0x44, Rock Tunnel, Vermilion, ...
MT_MOON_MAPS = frozenset({0x3B, 0x3C, 0x3D})  # 1F, B1F, B2F
DUNGEON_MAPS = MT_MOON_MAPS  # no training gate inside: grind outside (Route 3/4), inside head for the exit
POKECENTER_MAP = 41  # Viridian City's Pokecenter (door at Viridian (23,26)); learned in maps.json, same layout as every center


class WorldGraph:
    """Nodes are (map, x, y). Edges: visited neighbours not separated by a confirmed wall, plus warps."""

    def __init__(self, maps: dict):
        self.maps = maps

    blocked_now: frozenset = frozenset()  # (map, x, y) tiles an NPC temporarily occupies: skipped, never learned

    strict = True  # False = optimistic: ignore learned walls (some are false, learned behind an NPC or a fade)

    def static_npc_tiles(self, m: int) -> set:
        """Tiles of NPCs that never move and were always seen on ONE tile (cached per map)."""
        cache = self.__dict__.setdefault("_npc_cache", {})
        if m not in cache:
            tiles = set()
            for e in self.maps.get(str(m), {}).get("npcs", {}).values():
                pos = e.get("positions") or {}
                if not e.get("moves") and len(pos) == 1:
                    x, y = next(iter(pos)).split(",")
                    tiles.add((int(x), int(y)))
            cache[m] = tiles
        return cache[m]

    def neighbours(self, node):
        m, x, y = node
        d = self.maps.get(str(m))
        if not d:
            return
        for name, (dx, dy) in DIRS.items():
            key = f"{x},{y},{name}"
            warp = d.get("warps", {}).get(key)
            if warp:
                yield (warp[0], warp[1], warp[2]), name
                continue
            jump = d.get("jumps", {}).get(key)
            if jump:  # a learned ledge: one-way hop to a tile more than one step away
                yield (m, jump[0], jump[1]), name
                continue
            if self.strict and key in d.get("blocked", []):
                continue
            nx, ny = x + dx, y + dy
            if (m, nx, ny) in self.blocked_now:
                continue
            if (nx, ny) in self.static_npc_tiles(m):
                continue  # a person standing there: walking into them only starts a conversation (Forest corridor, 07:34)
            if f"{nx},{ny}" in d.get("visited", {}):
                yield (m, nx, ny), name

    def path(self, start, goal_fn: Callable[[tuple], bool], limit: int = 5000) -> list[str] | None:
        """Strict BFS first; if no route, an optimistic one (walls ignored): a false wall gets re-tested and
        cleared on the way instead of leaving the agent with no plan (seen 2026-11-03: stuck at Mom)."""
        p = self._bfs(start, goal_fn, limit)
        if p is None and self.strict:
            self.strict = False
            try:
                p = self._bfs(start, goal_fn, limit)
            finally:
                self.strict = True
        return p

    def _bfs(self, start, goal_fn, limit):
        r = self._bfs_node(start, goal_fn, limit)
        return r[1] if r else None

    def _bfs_node(self, start, goal_fn, limit):
        """_bfs that also returns the goal node: (node, buttons) or None (buttons [] when start is the goal)."""
        prev = {start: None}
        q = deque([start])
        while q and len(prev) < limit:
            cur = q.popleft()
            if goal_fn(cur):
                out, node = [], cur
                while prev[node]:
                    node, btn = prev[node]
                    out.append(btn)
                return cur, out[::-1]
            for nxt, btn in self.neighbours(cur):
                if nxt not in prev:
                    prev[nxt] = (cur, btn)
                    q.append(nxt)
        return None


def interaction_spots(maps: dict, needle: str) -> list[tuple[int, int, int, str]]:
    """(map, x, y, facing) of recorded interactions whose text mentions `needle`."""
    out = []
    for mid, d in maps.items():
        for key, e in d.get("interactions", {}).items():
            hay = ((e.get("text") or "") + " " + " ".join(e.get("choices", []) or [])).lower()
            if needle.lower() in hay:
                x, y, f = key.split(",")
                out.append((int(mid), int(x), int(y), f))
    return out
