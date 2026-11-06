"""pickup_approach: close the gap to an item ball whose side tiles are not on the learned map yet.

The navigation graph only holds tiles the agent has stood on, so a ball in a side pocket (Route 2) has no
known route to any tile beside it. Walk to the visited tile with an unexplored side that is nearest the ball,
then step into the unexplored side that gets closest to it; each such step visits a new tile (or learns a wall).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pokeagent.explorer.perceive import DIRS

if TYPE_CHECKING:
    from pokeagent.explorer.context import ExplorerContext

APPROACH_STEPS = 60  # most approach presses per ball in one run before it is given up on


def _dist(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def approach_plan(ctx: "ExplorerContext", ball: tuple, budget: int) -> dict | None:
    """``{"ball", "approach": button, "steps": n}``: the next press toward ``ball`` through unexplored ground,
    when walking there plus the straight-line rest fits ``budget``; else None."""
    m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
    if ball[0] != m or ctx.pickup_approach.get(ball, 0) >= APPROACH_STEPS:
        return None
    target = (ball[1], ball[2])
    d = ctx.mem.m(m)
    visited, blocked = d["visited"], set(d["blocked"])
    graph = ctx.mem._frontier_graph()
    candidates = []

    def collect(node) -> bool:  # never "found": a full sweep of the reachable visited tiles
        if node[0] == m and ctx.mem._frontier(d, visited, blocked, node):
            candidates.append(node)
        return False

    graph._bfs_node((m, x, y), collect, 4000)
    if not candidates:
        return None
    best = min(candidates, key=lambda n: _dist((n[1], n[2]), (x, y)) + _dist((n[1], n[2]), target))
    route = ctx.mem.route_to(m, x, y, best)
    if route is None:
        return None
    buttons = route[1]
    steps = len(buttons) + _dist((best[1], best[2]), target)
    if steps > budget:
        return None
    if buttons:
        return {"ball": ball, "approach": buttons[0], "steps": steps}
    here = [(name, (best[1] + dx, best[2] + dy)) for name, (dx, dy) in DIRS.items()
            if f"{best[1]},{best[2]},{name}" not in blocked and f"{best[1] + dx},{best[2] + dy}" not in visited
            and f"{best[1]},{best[2]},{name}" not in d.get("warps", {})
            and f"{best[1]},{best[2]},{name}" not in d.get("jumps", {})]
    if not here:
        return None
    name, _tile = min(here, key=lambda t: _dist(t[1], target))
    return {"ball": ball, "approach": name, "steps": steps}
