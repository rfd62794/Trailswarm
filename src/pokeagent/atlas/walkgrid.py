"""walkgrid: where the player CAN walk on a map, straight from the ROM, and a BFS over it.

A map is blocks (4x4 tiles); the player steps in 2x2-tile cells and the game tests the bottom-left tile of the cell ahead
against the tileset's collision list (atlas.collision), so walkable(cell) = that tile id is in the list. Water, counters,
walls and trees are simply not in the list. Warp tiles (ladders, doors) and static objects (NPCs, trainers, balls) are
treated as obstacles on the way and allowed only as the goal. Learned walls (``walls``: "x,y,DIR" strings) and temporary NPC
blocks are EXTRA obstacles: they are tried first, and if they cut the goal off a second pass ignores them, so a false learned
wall can never block a route the ROM says exists. ``jumps`` (learned ledge hops, "x,y,DIR" -> [x, y]) are one-way edges.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache

import numpy as np

from pokeagent.atlas import rom_maps
from pokeagent.atlas.collision import walkable_ids
from pokeagent.atlas.tiles import load_tileset

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def walk_grid(rom: bytes, hd: rom_maps.MapHeader) -> np.ndarray:
    """(h*2, w*2) bool: cell (y, x) is walkable by the ROM collision list."""
    ids = list(walkable_ids(rom, hd.tileset))
    bs = load_tileset(rom, hd.tileset).blockset
    blocks = np.frombuffer(hd.blocks(rom), dtype=np.uint8)
    if blocks.size < hd.w * hd.h:
        blocks = np.pad(blocks, (0, hd.w * hd.h - blocks.size))
    blocks = blocks.reshape(hd.h, hd.w)
    tile = bs[blocks.astype(np.intp) % len(bs)][:, :, [1, 3]][:, :, :, [0, 2]]
    tile = tile.transpose(0, 2, 1, 3).reshape(hd.h * 2, hd.w * 2)
    return np.isin(tile, ids)


def bfs(grid: np.ndarray, start: tuple, goals: set, obstacles: set, walls: set, jumps: dict) -> list[str] | None:
    """Buttons from ``start`` (x, y) to the nearest of ``goals``; goals may stand on obstacle cells (warps)."""
    h, w = grid.shape
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur in goals and cur != start:
            out = []
            while prev[cur]:
                cur, btn = prev[cur]
                out.append(btn)
            return out[::-1]
        if cur in goals:
            return []
        for name, (dx, dy) in DIRS.items():
            key = f"{cur[0]},{cur[1]},{name}"
            if key in walls:
                continue
            jump = jumps.get(key)
            nxt = (jump[0], jump[1]) if jump else (cur[0] + dx, cur[1] + dy)
            if nxt in prev or not (0 <= nxt[0] < w and 0 <= nxt[1] < h):
                continue
            if not jump and not grid[nxt[1], nxt[0]] and nxt not in goals:
                continue
            if nxt in obstacles and nxt not in goals:
                continue
            prev[nxt] = (cur, name)
            q.append(nxt)
    return None


def rom_planner(rom_path: str = "roms/Pokemon Red.gb"):
    """``plan(map_id, start, goals, walls=(), blocked=(), jumps=None) -> [buttons] | None``; None when the ROM is unreadable
    or no route exists. ``start`` and ``goals`` are (x, y) cells; ``blocked`` are temporarily occupied (x, y) cells."""
    try:
        rom = rom_maps.load(rom_path)
    except OSError:
        return None

    @lru_cache(maxsize=None)
    def parts(map_id: int):
        hd = rom_maps.header(rom, map_id)
        warps = frozenset((x, y) for x, y, _dw, _dm in hd.warps)
        objs = frozenset((o["x"], o["y"]) for o in hd.objects)
        return walk_grid(rom, hd), warps, objs

    def plan(map_id: int, start: tuple, goals, walls=(), blocked=(), jumps=None):
        try:
            grid, warps, objs = parts(map_id)
        except Exception:  # an unparseable header must never end a run
            return None
        start, goals, jumps = tuple(start), {tuple(g) for g in goals}, jumps or {}
        keep = goals | {start}
        # Passes, strictest first: learned walls + temporary blocks + static objects; then ROM + objects; then ROM only (a
        # trainer or NPC standing in a corridor is something to talk to or fight, not a wall). Warp tiles are never stepped on
        # in passing. Learned walls and NPC blocks can therefore delay a ROM route but never remove it.
        for obstacles, w in ((warps | objs | set(blocked), set(walls)), (warps | objs, set()), (warps, set())):
            path = bfs(grid, start, goals, obstacles - keep, w, jumps)
            if path is not None:
                return path
        return None
    return plan


def rom_cave_planner(rom_path: str = "roms/Pokemon Red.gb", maps=frozenset({0x3B, 0x3C, 0x3D})):
    """A multi-floor planner over the ROM grids of ``maps`` (a dungeon): walking is a grid step, stepping on a warp tile
    arrives on the header's destination warp tile of the destination floor. ``plan(start, goals, walls=None, blocked=None)``:
    ``start`` is (map, x, y), ``goals`` a set of (map, x, y) cells (stepping onto one ends the route, so an exit warp can be a
    goal), ``walls``/``blocked`` map a floor id to learned "x,y,DIR" strings / temporarily occupied (x, y) cells. Returns the
    buttons for the whole chain (floor changes included) or None. Same pass order as ``rom_planner``: learned walls and
    NPC blocks first, then static objects only, then the bare ROM, so learned data never removes a ROM route."""
    try:
        rom = rom_maps.load(rom_path)
    except OSError:
        return None
    heads = {m: rom_maps.header(rom, m) for m in maps}
    grids = {m: walk_grid(rom, h) for m, h in heads.items()}
    warp_to: dict = {}
    for m, h in heads.items():
        for x, y, dw, dm in h.warps:
            dest = heads.get(dm)
            if dest is not None and dw < len(dest.warps):
                warp_to[(m, x, y)] = (dm, dest.warps[dw][0], dest.warps[dw][1])
            else:
                warp_to[(m, x, y)] = None  # a way out of the dungeon: only ever a goal
    objs = {m: frozenset((o["x"], o["y"]) for o in h.objects) for m, h in heads.items()}

    def search(start, goals, solid, walls, blocked):
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            m, x, y = cur
            for name, (dx, dy) in DIRS.items():
                if f"{x},{y},{name}" in walls.get(m, ()):
                    continue
                cell = (m, x + dx, y + dy)
                g = grids[m]
                if not (0 <= cell[1] < g.shape[1] and 0 <= cell[2] < g.shape[0]):
                    continue
                is_goal = cell in goals
                if not is_goal and (not g[cell[2], cell[1]] and cell not in warp_to):
                    continue
                if not is_goal and (cell[1:] in solid.get(m, ()) or cell[1:] in blocked.get(m, ())):
                    continue
                nxt = warp_to.get(cell, cell) if not is_goal else cell
                if nxt is None or nxt in prev:
                    continue
                prev[nxt] = (cur, name)
                if is_goal:
                    out, node = [], nxt
                    while prev[node]:
                        node, btn = prev[node]
                        out.append(btn)
                    return out[::-1]
                q.append(nxt)
        return None

    def plan(start, goals, walls=None, blocked=None):
        goals, start = {tuple(g) for g in goals}, tuple(start)
        if start[0] not in heads:
            return None
        for solid, w, b in ((objs, walls or {}, blocked or {}), (objs, {}, {}), ({}, {}, {})):
            path = search(start, goals, solid, w, b)
            if path is not None:
                return path
        return None
    def follow(start, buttons):
        """The (map, x, y) cells a button list visits from ``start`` (floor changes land on the destination warp tile)."""
        cur, seen = tuple(start), [tuple(start)]
        for b in buttons:
            cell = (cur[0], cur[1] + DIRS[b][0], cur[2] + DIRS[b][1])
            cur = warp_to.get(cell, cell) or cell
            seen.append(cur)
        return seen
    plan.follow = follow

    def warp_tiles(map_id: int, dest_map: int | None = None) -> set:
        """(map, x, y) of the warps on ``map_id`` that lead to ``dest_map`` (any destination when None)."""
        return {(map_id, x, y) for x, y, _dw, dm in heads[map_id].warps if dest_map is None or dm == dest_map}
    plan.warp_tiles = warp_tiles
    return plan
