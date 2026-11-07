"""par: the exact cheapest route across one map's grid, in frames (A* over 4-neighbour steps plus one-way ledge hops)."""
from __future__ import annotations

import heapq

from pokeagent.legs.grid import DIRS, FRAME_WALK, GRASS_PENALTY, Grid


def par(grid: Grid, start: tuple, goal: tuple, step: float = FRAME_WALK, grass_penalty: float = GRASS_PENALTY):
    """``(frames, path)`` from ``start`` to ``goal`` (x, y) cells, path = cells visited incl. both ends; None if unreachable.

    ``step`` is frames per tile (16 walking, 8 biking); entering grass adds ``grass_penalty``; a ledge hop costs two steps.
    Warp tiles are solid except as the start or goal (which may even be one).
    """
    start, goal = tuple(start), tuple(goal)
    if start == goal:
        return 0.0, [start]
    best, prev, heap = {start: 0.0}, {}, [(0.0, 0.0, start)]
    while heap:
        _f, g, cur = heapq.heappop(heap)
        if cur == goal:
            path = [cur]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return g, path[::-1]
        if g > best.get(cur, 1e18):
            continue
        for name, (dx, dy) in DIRS.items():
            if (cur[0], cur[1], name) in grid.walls:
                continue
            hop = grid.jumps.get((cur[0], cur[1], name))
            if hop:
                nxt, cost = hop, 2 * step
            else:
                nxt = (cur[0] + dx, cur[1] + dy)
                if not grid.inside(*nxt) or not grid.walk[nxt[1], nxt[0]] or (nxt in grid.solid and nxt != goal):
                    continue
                cost = step + (grass_penalty if grid.grass[nxt[1], nxt[0]] else 0.0)
            ng = g + cost
            if ng < best.get(nxt, 1e18):
                best[nxt], prev[nxt] = ng, cur
                heapq.heappush(heap, (ng + step * (abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1])), ng, nxt))
    return None


def map_par(get, map_id: int, start: tuple, goal: tuple, **kw):
    """``par`` on a ROM map; ``get`` is ``grid.rom_grids()``. None when the map or the route is unknown."""
    g = get(map_id) if get else None
    return par(g, start, goal, **kw) if g is not None else None
