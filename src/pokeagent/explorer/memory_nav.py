"""Where to step next, from the learned map: least-visited neighbour, then the nearest frontier tile.

Mixed into MapMemory (moved unchanged from tools/explore_demo.py).
"""
from __future__ import annotations

from pokeagent.explorer.perceive import DIRS, ahead_tiles
from pokeagent.explorer.world import WorldGraph

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
                if n not in tried and self.known_solid(tileset, ahead_tiles(tilemap, n)):
                    tried.append(n)
                    # remember it as a wall edge too: the frontier search only knows 'blocked', so without this it kept
                    # sending agents to a 'frontier' tile whose open side was a known-solid tile (move/A loop at Viridian)
                    if f"{x},{y},{n}" not in d["blocked"]:
                        d["blocked"].append(f"{x},{y},{n}")
                if grass == "avoid" and n not in tried and self.is_grass(tileset, ahead_tiles(tilemap, n)):
                    tried.append(n)
        for n in list(DIRS):  # do not take a connection/warp back to a map we are deliberately done with
            w = d["warps"].get(f"{x},{y},{n}")
            if w and avoid_maps and w[0] in avoid_maps and n not in tried:
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

    def _frontier_graph(self) -> WorldGraph:
        g = WorldGraph(self.data["maps"]); g.strict = True
        return g

    def _frontier(self, d: dict, visited: dict, blocked: set, n: tuple) -> bool:
        """A tile that still has an unexplored side (same predicate the demo's frontier_step used)."""
        for name, (dx, dy) in DIRS.items():
            if f"{n[1]},{n[2]},{name}" not in blocked and f"{n[1] + dx},{n[2] + dy}" not in visited \
                    and f"{n[1]},{n[2]},{name}" not in d.get("warps", {})                     and f"{n[1]},{n[2]},{name}" not in d.get("jumps", {}):  # a ledge tile is hopped over, never visited
                return True
        return False

    def is_frontier(self, node: tuple) -> bool:
        """True while `node` (map, x, y) still has an unexplored side."""
        m = self.data["maps"].get(str(node[0]))
        if not m:
            return False
        return self._frontier(m, m.get("visited", {}), set(m.get("blocked", [])), node)

    def frontier_plan(self, map_id, x, y):
        """(target node, buttons) of the nearest frontier tile on this map, or None."""
        d = self.m(map_id); visited, blocked = d["visited"], set(d["blocked"])
        return self._frontier_graph()._bfs_node(
            (map_id, x, y), lambda n: n[0] == map_id and self._frontier(d, visited, blocked, n), 4000)

    def route_to(self, map_id, x, y, target: tuple):
        """Strict BFS route to one node: (node, buttons) or None."""
        return self._frontier_graph()._bfs_node((map_id, x, y), lambda n: n == target, 4000)

    def frontier_step(self, map_id, x, y) -> tuple[str, str] | None:
        """First step of the shortest known route to a tile that still has an unexplored side (big towns need
        this: local least-visited wandering never reaches the far side of Viridian)."""
        p = self.frontier_plan(map_id, x, y)
        if p and p[1]:
            return p[1][0], f"frontier: {len(p[1])} steps to the nearest tile with an unexplored side"
        return None
