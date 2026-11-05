"""BFS navigation over learned map memory (runs/maps.json).

The explorer's memory records visited tiles, direction-blocked edges and warps.
This turns it into a graph for two uses:
  - optimal-path measurement: BFS distance start -> goal ~= presses needed
  - potential fields for reward shaping (PBRS): Phi(s) = -distance-to-goal

Edges are treated as traversable when the target tile was visited and the
direction is not recorded blocked; warp edges connect maps. Distances use
reversed directed edges. These are learned-graph distances, not proven optimal
button counts: unknown edges, menus, facing and animation timing are omitted.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
HOUSE_MAPS = {37, 38}  # 0x25/0x26: Pallet interiors; "left the house" = any other map


def load_grids(path: str | Path = "runs/maps.json") -> dict[int, dict]:
    data = json.loads(Path(path).read_text()).get("maps", {})
    grids = {}
    for mid, d in data.items():
        grids[int(mid)] = {
            "tiles": {tuple(int(v) for v in k.split(",")) for k in d.get("visited", {})},
            "blocked": set(d.get("blocked", [])),
            "warps": {tuple(int(v) for v in k.rsplit(",", 1)[0].split(",")) + (k.rsplit(",", 1)[1],):
                      tuple(w) for k, w in d.get("warps", {}).items()},
        }
    return grids


def _neighbors(grids: dict[int, dict], node: tuple[int, int, int]):
    """Adjacent nodes reachable from (map,x,y); warps connect maps."""
    m, x, y = node
    g = grids.get(m)
    if g is None:
        return
    for dname, (dx, dy) in DIRS.items():
        if f"{x},{y},{dname}" in g["blocked"]:
            continue
        w = g["warps"].get((x, y, dname))
        if w is not None:
            yield (w[0], w[1], w[2])
            continue
        t = (x + dx, y + dy)
        if t in g["tiles"]:
            yield (m, t[0], t[1])


def distance_field(grids: dict[int, dict], goals) -> dict[tuple[int, int, int], int]:
    """BFS from goal nodes; returns {node: steps-to-nearest-goal}.

    goals: iterable of (map,x,y) nodes, or ('map', id) to mean every visited
    tile on that map, or ('!house',) for every visited tile off the house maps.
    """
    starts = []
    for g in goals:
        if g == ("!house",):
            for mid, gg in grids.items():
                if mid not in HOUSE_MAPS:
                    starts += [(mid, x, y) for x, y in gg["tiles"]]
        elif isinstance(g, tuple) and len(g) == 2 and g[0] == "map":
            gg = grids.get(g[1])
            if gg:
                starts += [(g[1], x, y) for x, y in gg["tiles"]]
        else:
            starts.append(tuple(g))
    dist = {s: 0 for s in starts if s[0] in grids}
    reverse = {}
    for mid, grid in grids.items():
        for x, y in grid['tiles']:
            node = (mid, x, y)
            for target in _neighbors(grids, node):
                reverse.setdefault(target, []).append(node)
    q = deque(dist)
    while q:
        n = q.popleft()
        for nb in reverse.get(n, ()):
            if nb not in dist:
                dist[nb] = dist[n] + 1
                q.append(nb)
    return dist


def optimal_steps(grids, start, goals) -> int | None:
    return distance_field(grids, goals).get(tuple(start))


def potential(dist: dict, default: float | None = None):
    """Phi(s) = -dist(s): closer to goal = higher potential. Unknown -> None
    (caller skips shaping that transition)."""
    def phi(obs) -> float | None:
        d = dist.get((obs[0], obs[1], obs[2]))
        return -d if d is not None else default
    return phi
