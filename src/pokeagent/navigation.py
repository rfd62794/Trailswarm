"""Deterministic navigation over the learned map memory (runs/maps.json).

The map graph is knowledge the explorers already earned: 'visited' tiles are
walkable, 'blocked' edges are confirmed walls. BFS here means the agent never
re-learns geometry a map already answers.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from pokeagent.game.stores import store_path

DIRS = {'UP': (0, -1), 'DOWN': (0, 1), 'LEFT': (-1, 0), 'RIGHT': (1, 0)}
BUTTON = {'UP': 0, 'DOWN': 1, 'LEFT': 2, 'RIGHT': 3}


def load_memory(path: str = store_path("runs/maps.json").as_posix()) -> dict:  # POKEAGENT_GAME read once at def time
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def shortest_path(memory: dict, map_id: int, x: int, y: int, tx: int, ty: int,
                  tmap: int | None = None, nearest: bool = False):
    """BFS over learned memory -> list of action indices, or None if unreachable.

    States are (map, x, y): walkable moves inside a map plus warp edges
    'x,y,dir' -> [m1, x1, y1] and one-way ledge jumps 'x,y,dir' -> [x1, y1],
    so a route can hop doors/stairs across maps and drop down ledges.
    """
    tmap = map_id if tmap is None else tmap
    goal = (tmap, tx, ty)
    start = (map_id, x, y)
    if start == goal:
        return []
    maps = memory.get('maps', {})
    q = deque([start])
    prev = {start: None}
    found = None
    while q:
        m, cx, cy = q.popleft()
        d = maps.get(str(m), {})
        visited = set(d.get('visited', {}))
        blocked = set(d.get('blocked', []))
        warps = d.get('warps', {})
        jumps = d.get('jumps', {})
        for name, (dx, dy) in DIRS.items():
            key = f'{cx},{cy},{name}'
            if key in warps:  # observed transition beats a stale 'blocked' (fade artifacts)
                m1, x1, y1 = warps[key]
                nxt = (m1, x1, y1)
                known = True
            elif key in jumps:  # a recorded ledge jump: one-way edge, the landing counts as known
                x1, y1 = jumps[key]
                nxt = (m, x1, y1)
                known = True
            elif key in blocked:
                continue
            else:
                nxt = (m, cx + dx, cy + dy)
                known = False
            if nxt in prev:
                continue
            if not known and nxt != goal and nxt[0] == m and f'{nxt[1]},{nxt[2]}' not in visited:
                continue  # only learned-walkable tiles; warp and ledge landings count as known
            prev[nxt] = (m, cx, cy, name)
            if nxt == goal:
                found = nxt
                q.clear()
                break
            q.append(nxt)

    def _path(n):
        out = []
        cur = n
        while prev[cur] is not None:
            pm, px, py, b = prev[cur]
            out.append(BUTTON[b])
            cur = (pm, px, py)
        return out[::-1]

    if found:
        return _path(found)
    if nearest and prev:  # goal beyond known space: ride toward it at the MAP level first
        dist = {tmap: 0}
        mq = deque([tmap])
        while mq:  # warp-graph distance from each map to the target map
            cur = mq.popleft()
            for mid, md in maps.items():
                for dest in (md.get('warps') or {}).values():
                    if dest[0] == cur and int(mid) not in dist:
                        dist[int(mid)] = dist[cur] + 1
                        mq.append(int(mid))
        best = min(prev, key=lambda n: (dist.get(n[0], 999),
                                        abs(n[1] - tx) + abs(n[2] - ty) if n[0] == tmap else 0))
        return _path(best) if best != start else None
    return None
