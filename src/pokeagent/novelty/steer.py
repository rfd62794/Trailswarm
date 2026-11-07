"""Frontier steering for explorer-role agents: among the nearest frontier tiles, prefer the one whose unexplored side
is rarest across the swarm. A small additive term (at most PULL steps of detour), so distance still dominates."""
from __future__ import annotations

PULL = 6.0       # steps of extra walking a globally-unseen frontier tile is worth
CANDIDATES = 8   # nearest frontier tiles considered (BFS order)
DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def active(ctx) -> bool:
    """Steering is on only for the explorer role with a tracker attached; every other run is untouched."""
    nv = getattr(ctx, "novelty", None)
    return nv is not None and ctx.opts.role == "explorer" and nv.rewarding


def side_rarity(ctx, node: tuple) -> float:
    """The rarest unexplored neighbour tile of a frontier tile: 1.0 when no run has stood there."""
    mem = ctx.mem
    d = mem.m(node[0])
    visited, blocked, warps = d["visited"], set(d["blocked"]), d.get("warps", {})
    best = 0.0
    for name, (dx, dy) in DIRS.items():
        key = f"{node[1]},{node[2]},{name}"
        if key in blocked or key in warps or f"{node[1] + dx},{node[2] + dy}" in visited:
            continue
        best = max(best, ctx.novelty.rarity(f"t:{node[0]}:{node[1] + dx}:{node[2] + dy}"))
    return best


def plan(ctx, m: int, x: int, y: int):
    """(node, route) like ``MapMemory.frontier_plan`` but weighing rarity; None when there is no candidate (caller falls back)."""
    mem = ctx.mem
    d = mem.m(m)
    visited, blocked = d["visited"], set(d["blocked"])
    cands: list = []

    def collect(node) -> bool:  # never "found": a full sweep, nearest first
        if node[0] == m and mem._frontier(d, visited, blocked, node):
            cands.append(node)
        return len(cands) >= CANDIDATES

    mem._frontier_graph()._bfs_node((m, x, y), collect, 4000)
    best = None
    for node in cands:
        r = mem.route_to(m, x, y, node)
        if r is None or not r[1]:
            continue
        score = len(r[1]) - PULL * side_rarity(ctx, node)
        if best is None or score < best[0]:
            best = (score, node, r[1])
    return None if best is None else (best[1], best[2])
