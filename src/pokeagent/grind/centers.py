"""Round-trip cost from a map to the nearest Pokecenter, over a map graph. Pure (the graph comes from the caller)."""
from __future__ import annotations

import heapq


def center_costs(graph: dict[int, dict[int, float]], centers) -> dict[int, float]:
    """Cheapest frames from every map to any Pokecenter map. ``graph[a][b]`` = frames crossing a into b (treated as symmetric)."""
    adj: dict[int, dict[int, float]] = {}
    for a, nb in graph.items():
        for b, c in nb.items():
            for x, y in ((a, b), (b, a)):
                if c < adj.setdefault(x, {}).get(y, 1e18):
                    adj[x][y] = c
    best = {c: 0.0 for c in centers}
    heap = [(0.0, c) for c in centers]
    heapq.heapify(heap)
    while heap:
        d, m = heapq.heappop(heap)
        if d > best.get(m, 1e18):
            continue
        for n, c in adj.get(m, {}).items():
            if d + c < best.get(n, 1e18):
                best[n] = d + c
                heapq.heappush(heap, (d + c, n))
    return best
