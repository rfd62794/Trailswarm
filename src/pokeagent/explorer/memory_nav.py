"""Where to step next, from the learned map: least-visited neighbour, then the nearest frontier tile.

Mixed into MapMemory (moved unchanged from tools/explore_demo.py).
"""
from __future__ import annotations

from pokeagent.explorer.perceive import DIRS, ahead_tiles, stand_tile
from pokeagent.explorer.world import WorldGraph, maps_version, route_maps_version

OPPOSITE = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}


class NavMixin:
    def choose(self, map_id, x, y, facing: str, tilemap: bytes | None = None, tileset: int = 0,
               avoid_maps: set | None = None, grass: str = "neutral", last_dir: str | None = None,
               tabu: set | None = None, reverse_penalty: int = 2) -> tuple[str, str]:
        """grass: 'seek' (training: prefer grass ahead), 'avoid' (weak: never step into known grass), 'neutral'."""
        name, why, want_frontier = self.choose_local(map_id, x, y, facing, tilemap, tileset,
                                                     avoid_maps, grass, last_dir, tabu, reverse_penalty)
        if want_frontier:
            step = self.frontier_step(map_id, x, y)
            if step:
                return step
        return name, why

    def choose_local(self, map_id, x, y, facing: str, tilemap: bytes | None = None, tileset: int = 0,
                     avoid_maps: set | None = None, grass: str = "neutral", last_dir: str | None = None,
                     tabu: set | None = None, reverse_penalty: int = 2) -> tuple[str, str, bool]:
        """The per-tile greedy pick. Returns (button, why, want_frontier): want_frontier is True when every
        neighbour was already seen, i.e. the caller should route to a frontier tile instead of wandering.

        Momentum: a direction opposite the last successful move (``last_dir``) scores ``reverse_penalty``
        visits extra, and a neighbour in ``tabu`` (tiles stood on recently) scores one extra. Ties prefer
        continuing straight (``last_dir``), then the fixed UP/DOWN/LEFT/RIGHT order."""
        d = self.m(map_id); best = None
        tried = [n for n in DIRS if f"{x},{y},{n}" in d["blocked"]]
        if tilemap is not None:  # tile ids ahead already known solid (bookshelf, wall, desk) count as tried
            for n in DIRS:
                if n not in tried and self.known_solid(tileset, ahead_tiles(tilemap, n), stand_tile(tilemap)):
                    tried.append(n)
                    # remember it as a wall edge too: the frontier search only knows 'blocked', so without this it kept
                    # sending agents to a 'frontier' tile whose open side was a known-solid tile (move/A loop at Viridian)
                    if f"{x},{y},{n}" not in d["blocked"]:
                        d["blocked"].append(f"{x},{y},{n}")
                if grass == "avoid" and n not in tried and self.is_grass(tileset, ahead_tiles(tilemap, n)):
                    tried.append(n)
        for n, (tdx, tdy) in DIRS.items():  # a wanderer NPC temporarily stands there: wait or go around, do not learn a wall
            if (map_id, x + tdx, y + tdy) in self.temp_blocked and n not in tried:
                tried.append(n)
        for n in list(DIRS):  # do not take a connection/warp back to a map we are deliberately done with
            key = f"{x},{y},{n}"
            w = d["warps"].get(key)
            if avoid_maps and n not in tried and (
                    (w is not None and w[0] in avoid_maps)
                    or (w is None and getattr(avoid_maps, "leads_out", None) is not None
                        and avoid_maps.leads_out(map_id, key))):  # one-sighting/recorded edge off the set
                tried.append(n)
        # Something blocks the way we face and we never talked to it: that is an interaction point candidate.
        fdx, fdy = DIRS.get(facing, (0, 0))
        npc_ahead = self.npc_at(map_id, x + fdx, y + fdy)
        if npc_ahead is not None and facing in tried and not npc_ahead.get("talked") and f"{x},{y},{facing}" not in self.recent_talk:
            return "A", f"an NPC we have not talked to is in front (pic {npc_ahead['pic']}): pressing A", False
        if npc_ahead is not None:
            pass  # a person: never treated as an object to probe again, and never learned as a wall tile
        elif facing in tried and not self.interaction_known(map_id, x, y, facing) and f"{x},{y},{facing}" not in self.recent_talk:
            return "A", f"at ({x},{y}) facing {facing} is blocked and untested: pressing A to see if it talks", False
        for i, (name, (dx, dy)) in enumerate(DIRS.items()):
            if name in tried:
                continue
            warp = d["warps"].get(f"{x},{y},{name}")
            if warp:  # a warp leads off this map: score it by how often we already took it, not by an off-map tile
                base = d.get("warp_taken", {}).get(f"{x},{y},{name}", 1) * 3
            else:
                jump = d.get("jumps", {}).get(f"{x},{y},{name}")  # a ledge: judge it by where it lands, not the hopped tile
                base = d["visited"].get(f"{jump[0]},{jump[1]}" if jump else f"{x + dx},{y + dy}", 0)
                if grass == "seek" and tilemap is not None and self.is_grass(tileset, ahead_tiles(tilemap, name)):
                    base = -1  # training: grass first
            score = base + (1 if not warp and tabu and (x + dx, y + dy) in tabu else 0)
            if last_dir and name == OPPOSITE.get(last_dir):
                score += reverse_penalty
            key = (score, 0 if name == last_dir else 1, i)
            if best is None or key < best[0]:
                best = (key, name, base)
        if best is None:
            return "A", "every direction known blocked: pressing A to look around", False
        why = f"at ({x},{y}) blocked={tried or 'none'}; {best[1]} leads to a tile seen {best[2]}x"
        return best[1], why, best[2] > 0

    def _env_version(self) -> tuple:
        """What a goal predicate can read OUTSIDE the maps edge data - the temp-blocked tiles, every
        never-moving NPC's last position and the beaten-trainer set."""
        npc_last = frozenset(
            (mid, tuple(e["last"]))
            for mid, d in self.data["maps"].items()
            for e in d.get("npcs", {}).values()
            if not e.get("moves") and e.get("last"))
        beaten = getattr(self, "beaten_tiles", None)
        tiles = beaten() if callable(beaten) else beaten
        return (frozenset(self.temp_blocked), npc_last, frozenset(tiles) if tiles else ())

    def _mem_version(self) -> tuple:
        """Route-cache validity for the shared graph and neighbour memo: the FULL maps fingerprint
        (learned walls included - neighbours must see them) plus the goal-visible environment."""
        return (maps_version(self.data["maps"]),) + self._env_version()

    def _visited_total(self) -> int:
        return sum(len(d.get("visited", ())) for d in self.data["maps"].values())

    def _route_graph(self, allowed=None, version=None) -> WorldGraph:
        """The routing graph for the current memory version, shared by the step's searches: one wall,
        warp, jump, static-NPC or temp-blocked change rebuilds it (and its neighbour-memo key rolls),
        while an unchanged version keeps the same graph and its warmed cache. ``visited`` is not in
        the version: new tiles only grow the graph, they do not invalidate it."""
        v = version or self._mem_version()
        key = frozenset(allowed) if allowed is not None else None
        cache = self.__dict__.setdefault("_route_graphs", {})
        ent = cache.get(key)
        if ent is None or ent[0] != v:
            g = WorldGraph(self.data["maps"]); g.strict = True
            g.blocked_now = frozenset(self.temp_blocked)
            g.allowed_maps = key
            g.__dict__["_mv"] = v[0]
            cache[key] = ent = (v, g)
        return ent[1]

    def cached_route(self, start, goal_key, goal_fn, *, allowed=None, limit=4000):
        """``_bfs_node`` with a last-result cache keyed on ``goal_key``: while the route version
        holds, the cached path's own edges stay open and its goal still holds, its remaining suffix
        answers without a new search; a wall ON the path, a warp/jump/NPC/temp-blocked/beaten change,
        stepping off the path, or a visited-reading goal gone stale re-runs it. A cached miss also
        needs the full memory version and the visited total: only those can open a route that was
        not there."""
        env = self._env_version()
        v = (maps_version(self.data["maps"]),) + env
        vr = (route_maps_version(self.data["maps"]),) + env
        seen = self._visited_total()
        routes = self.__dict__.setdefault("_routes", {})
        c = routes.get(goal_key)
        if c is not None and c["version"] == vr:
            nodes = c["nodes"]
            if nodes is None:
                if start == c["start"] and c["full"] == v and c["seen"] == seen:
                    return None
            elif start in nodes:
                i = nodes.index(start)
                g = self._route_graph(allowed, v)
                if g._suffix_edges_ok(nodes, c["buttons"], i) and goal_fn(nodes[-1]):
                    return nodes[-1], list(c["buttons"][i:])
        r = self._route_graph(allowed, v)._bfs_route(start, goal_fn, limit)
        if len(routes) > 32:
            routes.clear()
        routes[goal_key] = {"version": vr, "full": v, "seen": seen, "start": start,
                            "nodes": None if r is None else tuple(r[0]),
                            "buttons": None if r is None else tuple(r[1])}
        return None if r is None else (r[0][-1], r[1])

    def _frontier_graph(self, allowed=None) -> WorldGraph:
        return self._route_graph(allowed)

    def _frontier(self, d: dict, visited: dict, blocked: set, n: tuple) -> bool:
        """A tile that still has an unexplored side (same predicate the demo's frontier_step used)."""
        for name, (dx, dy) in DIRS.items():
            key = f"{n[1]},{n[2]},{name}"
            if self._person_tile(n[0], n[1] + dx, n[2] + dy):
                continue  # a person's tile is never 'visited', so it would stay a frontier forever (Route 24 bridge trainer)
            if (key not in blocked and f"{n[1] + dx},{n[2] + dy}" not in visited
                    and key not in d.get("warps", {})
                    and key not in d.get("jumps", {})):  # a ledge tile is hopped over, never visited
                return True
        return False

    def _person_tile(self, map_id: int, x: int, y: int) -> bool:
        """A person is standing there now (temp_blocked), a stationary NPC was last seen there, or the
        tile is a beaten trainer's ROM placement still held by its NPC."""
        if (map_id, x, y) in self.temp_blocked:
            return True
        npc = self.npc_at(map_id, x, y)
        if npc is not None and npc.get("moves") is False:
            return True
        return self._beaten_trainer_tile(map_id, x, y)

    def _beaten_trainer_tile(self, map_id: int, x: int, y: int) -> bool:
        """A ROM placement the ledger calls beaten, with an NPC recorded on or next to it (the NPC may
        have moved off the placement when it walked up to fight: check every recorded position, not last)."""
        beaten = getattr(self, "beaten_tiles", None)
        if beaten is None:
            return False
        tiles = beaten() if callable(beaten) else beaten
        if (map_id, x, y) not in tiles:
            return False
        for e in self.m(map_id).get("npcs", {}).values():
            for p in (e.get("positions") or {}):
                try:
                    px, py = (int(v) for v in str(p).split(","))
                except ValueError:
                    continue
                if max(abs(px - x), abs(py - y)) <= 1:
                    return True
        return False

    def is_frontier(self, node: tuple) -> bool:
        """True while `node` (map, x, y) still has an unexplored side."""
        m = self.data["maps"].get(str(node[0]))
        if not m:
            return False
        return self._frontier(m, m.get("visited", {}), set(m.get("blocked", [])), node)

    def frontier_plan(self, map_id, x, y, allowed=None):
        """(target node, buttons) of the nearest frontier tile on this map, or None. ``allowed`` bounds the
        route's intermediate maps (a grind episode's map set): the plan may never leave it."""
        d = self.m(map_id); visited, blocked = d["visited"], set(d["blocked"])
        return self.cached_route((map_id, x, y),
                                 ("frontier", map_id, frozenset(allowed) if allowed is not None else None),
                                 lambda n: n[0] == map_id and self._frontier(d, visited, blocked, n),
                                 allowed=allowed)

    def route_to(self, map_id, x, y, target: tuple):
        """Strict BFS route to one node: (node, buttons) or None."""
        return self.cached_route((map_id, x, y), ("to", target), lambda n: n == target)

    def frontier_step(self, map_id, x, y) -> tuple[str, str] | None:
        """First step of the shortest known route to a tile that still has an unexplored side (big towns need
        this: local least-visited wandering never reaches the far side of Viridian)."""
        p = self.frontier_plan(map_id, x, y)
        if p and p[1]:
            return p[1][0], f"frontier: {len(p[1])} steps to the nearest tile with an unexplored side"
        return None
