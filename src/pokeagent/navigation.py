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


def shortest_path(memory: dict, map_id: int, x: int, y: int, tx: int, ty: int,
                  tmap: int | None = None):
    """BFS over learned memory -> list of action indices, or None if unreachable.

    States are (map, x, y): walkable moves inside a map plus warp edges
    'x,y,dir' -> [m1, x1, y1], so a route can hop doors/stairs across maps.
    """
    tmap = map_id if tmap is None else tmap
    goal = (tmap, tx, ty)
    start = (map_id, x, y)
    if start == goal:
        return []
    maps = memory.get('maps', {})
    q = deque([start])
    prev = {start: None}
    while q:
        m, cx, cy = q.popleft()
        d = maps.get(str(m), {})
        visited = set(d.get('visited', {}))
        blocked = set(d.get('blocked', []))
        warps = d.get('warps', {})
        for name, (dx, dy) in DIRS.items():
            key = f'{cx},{cy},{name}'
            if key in warps:  # observed transition beats a stale 'blocked' (fade artifacts)
                m1, x1, y1 = warps[key]
                nxt = (m1, x1, y1)
            elif key in blocked:
                continue
            else:
                nxt = (m, cx + dx, cy + dy)
            if nxt in prev:
                continue
            if nxt != goal and nxt[0] == m and f'{nxt[1]},{nxt[2]}' not in visited:
                continue  # only learned-walkable tiles; warp landings count as known
            prev[nxt] = (m, cx, cy, name)
            if nxt == goal:
                path = []
                cur = nxt
                while prev[cur] is not None:
                    pm, px, py, b = prev[cur]
                    path.append(BUTTON[b])
                    cur = (pm, px, py)
                return path[::-1]
            q.append(nxt)
    return None
