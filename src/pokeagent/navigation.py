"""Deterministic navigation over the learned map memory (runs/maps.json).

The map graph is knowledge the explorers already earned: 'visited' tiles are
walkable, 'blocked' edges are confirmed walls. BFS here means the agent never
re-learns geometry a map already answers.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

DIRS = {'UP': (0, -1), 'DOWN': (0, 1), 'LEFT': (-1, 0), 'RIGHT': (1, 0)}
BUTTON = {'UP': 0, 'DOWN': 1, 'LEFT': 2, 'RIGHT': 3}


def load_memory(path: str = 'runs/maps.json') -> dict:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def shortest_path(memory: dict, map_id: int, x: int, y: int, tx: int, ty: int):
    """BFS over learned memory -> list of action indices, or None if unreachable."""
    m = memory.get('maps', {}).get(str(map_id), {})
    visited = set(m.get('visited', {}))
    blocked = set(m.get('blocked', []))
    if (x, y) == (tx, ty):
        return []
    q = deque([(x, y)])
    prev = {(x, y): None}
    while q:
        cx, cy = q.popleft()
        for name, (dx, dy) in DIRS.items():
            if f'{cx},{cy},{name}' in blocked:
                continue
            nxt = (cx + dx, cy + dy)
            if nxt in prev:
                continue
            if nxt != (tx, ty) and f'{nxt[0]},{nxt[1]}' not in visited:
                continue  # only step onto learned-walkable tiles (target itself allowed)
            prev[nxt] = (cx, cy, name)
            if nxt == (tx, ty):
                path = []
                cur = nxt
                while prev[cur] is not None:
                    px, py, d = prev[cur]
                    path.append(BUTTON[d])
                    cur = (px, py)
                return path[::-1]
            q.append(nxt)
    return None
