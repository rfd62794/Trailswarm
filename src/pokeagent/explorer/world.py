"""World graph over the learned map memory: BFS across floors and doors (moved from tools/explore_plan.py)."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Callable

from pokeagent.explorer.route_cache import (
    _CACHE_CAP, _NEIGH, _ROUTES, _goal_sig, maps_version, route_maps_version)


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
SHIP_MAPS = frozenset(range(0x5E, 0x69))  # Vermilion dock + S.S. Anne decks/rooms (0x5E..0x68): no grass, no training gate
POKECENTER_MAP = 41  # Viridian City's Pokecenter (door at Viridian (23,26)); learned in maps.json, same layout as every center


class WorldGraph:
    """Nodes are (map, x, y). Edges: visited neighbours not separated by a confirmed wall, plus warps."""

    def __init__(self, maps: dict):
        self.maps = maps

    blocked_now: frozenset = frozenset()  # (map, x, y) tiles an NPC temporarily occupies: skipped, never learned

    strict = True  # False = optimistic: ignore learned walls (some are false, learned behind an NPC or a fade)

    allowed_maps: frozenset | None = None  # when set, BFS never steps onto a node outside it (grind-episode boundary)

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

    def _version(self) -> int:
        """The memory fingerprint this graph's caches key on. Computed once per graph (a graph is
        per-search); NavMixin re-stamps ``_mv`` on its long-lived shared graph when memory changes."""
        v = self.__dict__.get("_mv")
        if v is None:
            v = self.__dict__["_mv"] = maps_version(self.maps)
        return v

    def _route_version(self) -> int:
        """The last-result route cache's fingerprint: ``maps_version`` minus learned walls. A wall
        anywhere still rolls ``_version`` (fresh neighbours, graph rebuilds); whether it may roll a
        cached ROUTE is decided per path by ``_edge_still_open``."""
        v = self.__dict__.get("_rv")
        if v is None:
            v = self.__dict__["_rv"] = route_maps_version(self.maps)
        return v

    def _visited_total(self) -> int:
        """Tiles stood on across every map: a cached MISS is only trusted while this holds - a new
        tile is a new edge, and only a new edge can open a route that was not there."""
        return sum(len(d.get("visited", ())) for d in self.maps.values())

    def _edge_still_open(self, a, btn, b) -> bool:
        """Is the cached step ``a --btn--> b`` still a live edge? Only the learned-wall term needs a
        live check: warps, jumps and static-NPC tiles are inside ``_route_version`` (a change there
        already missed the cache key), temp-blocked tiles are in the key, ``visited`` only grows,
        and a warp/jump edge short-circuits exactly like ``_neighbours`` does."""
        m, x, y = a
        d = self.maps.get(str(m))
        if not d:
            return False
        key = f"{x},{y},{btn}"
        if key in d.get("warps", {}) or key in d.get("jumps", {}):
            return True
        return not (self.strict and key in d.get("blocked", []))

    def _suffix_edges_ok(self, nodes, buttons, i) -> bool:
        """Every edge of the cached suffix ``nodes[i:]`` (parallel ``buttons``) is still open."""
        return all(self._edge_still_open(nodes[j], buttons[j], nodes[j + 1])
                   for j in range(i, len(nodes) - 1))

    def _neigh_memo(self) -> dict:
        """This graph's slice of the shared neighbour memo, keyed on everything an edge can read:
        memory version, strict, the temp-blocked tiles and the allowed-map bound."""
        key = (id(self.maps), self._version(), self.strict, self.blocked_now, self.allowed_maps)
        ent = _NEIGH.get(key)
        if ent is None or ent[0] is not self.maps:
            if len(_NEIGH) >= _CACHE_CAP:
                _NEIGH.clear()
            ent = _NEIGH[key] = (self.maps, {})
        return ent[1]

    def neighbours(self, node):
        out = self._neigh_memo().get(node)
        if out is None:
            out = self._neigh_memo()[node] = list(self._neighbours(node))
        yield from out

    def _neighbours(self, node):
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

    def edges(self, node):
        """neighbours() filtered by allowed_maps: a grind episode's map set bounds the search."""
        for nxt, name in self.neighbours(node):
            if self.allowed_maps is None or nxt[0] in self.allowed_maps:
                yield nxt, name

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

    last_route: tuple | None = None  # (start, goal node, buttons) of the latest successful path(); par_follow reads the planner's target here

    def _bfs(self, start, goal_fn, limit):
        # _bfs_route, not _bfs_node: a cache hit must not even enter the counted search entry point.
        r = self._bfs_route(start, goal_fn, limit)
        if r and r[1]:
            WorldGraph.last_route = (start, r[0][-1], r[1])
        return r[1] if r else None

    def _route_key(self, goal_fn, limit) -> tuple | None:
        """The last-result cache key for a repeatable goal, or None for a goal with no stable
        signature (one that reads mutable state must re-search every call)."""
        sig = _goal_sig(goal_fn)
        if sig is None:
            return None
        return (id(self.maps), self._route_version(), self.strict, self.blocked_now,
                self.allowed_maps, sig, limit)

    def _bfs_route(self, start, goal_fn, limit):
        """(nodes, buttons) of the BFS path start->goal, or None.

        The last route per (goal signature, route version, blocked_now, bound) is kept: visiting new
        tiles no longer rolls the key - it only grows the graph - so a hit now re-validates the cached
        suffix's own edges (``_suffix_edges_ok``: a wall ON the path forces a re-search, one far away
        stays a hit) and re-asks the CURRENT goal_fn about the cached target (a frontier tile whose
        unexplored side just got visited stops answering, exactly like a fresh search would see).
        Stepping off the path re-runs the search. A cached MISS additionally requires the full memory
        version and the visited total to hold: only a new tile or a removed wall can open a route
        that was not there."""
        key = self._route_key(goal_fn, limit)
        full, seen = self._version(), self._visited_total()
        if key is not None:
            ent = _ROUTES.get(key)
            if ent is not None and ent[0] is self.maps:
                src, nodes, buttons, full_v, seen_v = ent[1:]
                if nodes is None:
                    if start == src and full_v == full and seen_v == seen:
                        return None
                elif start in nodes:
                    i = nodes.index(start)
                    if self._suffix_edges_ok(nodes, buttons, i) and goal_fn(nodes[-1]):
                        return list(nodes[i:]), list(buttons[i:])
        r = self._bfs_walk(start, goal_fn, limit)
        if key is not None:
            if len(_ROUTES) >= _CACHE_CAP:
                _ROUTES.clear()
            _ROUTES[key] = (self.maps, start, None if r is None else tuple(r[0]),
                            None if r is None else tuple(r[1]), full, seen)
        return r

    def _bfs_node(self, start, goal_fn, limit):
        """_bfs that also returns the goal node: (node, buttons) or None (buttons [] when start is the goal)."""
        r = self._bfs_route(start, goal_fn, limit)
        return (r[0][-1], r[1]) if r else None

    def _bfs_walk(self, start, goal_fn, limit):
        """The search itself: first goal hit wins, path reconstructed from the parent table."""
        prev = {start: None}
        q = deque([start])
        while q and len(prev) < limit:
            cur = q.popleft()
            if goal_fn(cur):
                nodes, out, node = [cur], [], cur
                while prev[node]:
                    node, btn = prev[node]
                    nodes.append(node)
                    out.append(btn)
                return nodes[::-1], out[::-1]
            for nxt, btn in self.edges(cur):
                if nxt not in prev:
                    prev[nxt] = (cur, btn)
                    q.append(nxt)
        return None


def interaction_spots(maps: dict, needle: str) -> list[tuple[int, int, int, str]]:
    """(map, x, y, facing) of recorded interactions whose text mentions `needle`; an entry whose
    ``type`` equals it (case-insensitive) also matches, and type matches come before text-only ones."""
    typed, texted = [], []
    for mid, d in maps.items():
        for key, e in d.get("interactions", {}).items():
            x, y, f = key.split(",")
            if (e.get("type", "") or "").lower() == needle.lower():
                typed.append((int(mid), int(x), int(y), f))
                continue
            hay = ((e.get("text") or "") + " " + " ".join(e.get("choices", []) or [])).lower()
            if needle.lower() in hay:
                texted.append((int(mid), int(x), int(y), f))
    return typed + texted


PLAYER_HOUSE_MAPS = (0x25, 0x26)  # Red's house and bedroom: the parcel is never handed out there


def parcel_spots(maps: dict) -> list[tuple[int, int, int, str]]:
    """Spots where the OAK'S PARCEL was handed over, from recorded interactions. A bag/START-menu overlay is also recorded as
    the text of whatever the player faced ('OAK PARCEL | CANCEL | USE | This isn't yours to use'), and in Red's house that
    matched "OAK PARCEL" and sent every oaks_parcel run home to the bedroom (2026-11-07 15:00): those are not hand-overs."""
    menu = {(m, x, y, f) for m, x, y, f in interaction_spots(maps, "CANCEL")}
    out = []
    for s in interaction_spots(maps, "OAK PARCEL") + interaction_spots(maps, "PARCEL"):
        if s not in menu and s[0] not in PLAYER_HOUSE_MAPS and s not in out:
            out.append(s)
    return out
