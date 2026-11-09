"""Per-map walkable grid with frame costs, from the ROM decode (atlas.walkgrid / atlas.collision), or from ASCII for tests.

Cost model (frames): a walked tile costs FRAME_WALK (16; a bike would be FRAME_BIKE = 8). Entering a tall-grass tile adds the
encounter-risk penalty GRASS_PENALTY = ENCOUNTER_RATE * BATTLE_FRAMES (default 10% x 600 = 60). Ledges are one-way two-tile
hops (LEDGE_FRAMES). Warp tiles are solid (never walked over in passing; start and goal may be one). NPCs are ignored.
TODO: trainer line-of-sight tiles (a penalty unless the trainer is beaten).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from pokeagent.game.paths import default_rom

FRAME_WALK, FRAME_BIKE = 16, 8
ENCOUNTER_RATE, BATTLE_FRAMES = 0.10, 600
GRASS_PENALTY = ENCOUNTER_RATE * BATTLE_FRAMES
LEDGE_FRAMES = 2 * FRAME_WALK
DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
# pokered LedgeTiles (ROM 0x1A6CF, checked in tests): (facing, tile stood on, ledge tile in front). Overworld tileset (0) only.
LEDGES = {("DOWN", 0x2C, 0x37), ("DOWN", 0x39, 0x36), ("DOWN", 0x39, 0x37), ("LEFT", 0x2C, 0x27), ("LEFT", 0x39, 0x27),
          ("RIGHT", 0x2C, 0x0D), ("RIGHT", 0x2C, 0x1D), ("RIGHT", 0x39, 0x0D)}


@dataclass
class Grid:
    walk: np.ndarray                                     # (h, w) bool
    grass: np.ndarray                                    # (h, w) bool: tall grass (wild encounters)
    solid: set = field(default_factory=set)              # (x, y) warp tiles
    jumps: dict = field(default_factory=dict)            # (x, y, DIR) -> (x2, y2): one-way ledge hop
    walls: set = field(default_factory=set)              # (x, y, DIR) edges blocked though both cells are walkable

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.walk.shape[1] and 0 <= y < self.walk.shape[0]


def from_ascii(rows: list[str]) -> Grid:
    """'.' floor, 'g' grass, '#' wall, 'W' warp tile, 'v' ledge (hop DOWN over it from the cell above, landing below)."""
    h = len(rows)
    walk = np.array([[c in ".gW" for c in r] for r in rows])
    grass = np.array([[c == "g" for c in r] for r in rows])
    g = Grid(walk, grass, {(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c == "W"})
    for y, r in enumerate(rows):
        for x, c in enumerate(r):
            if c == "v" and 0 < y < h - 1 and walk[y - 1, x] and walk[y + 1, x]:
                g.jumps[(x, y - 1, "DOWN")] = (x, y + 1)
    return g


def from_rom(rom: bytes, hd) -> Grid:
    from pokeagent.atlas.collision import ENTRY, TILESET_TABLE, tile_pairs, walkable_ids
    from pokeagent.atlas.walkgrid import cell_tiles
    tiles = cell_tiles(rom, hd)
    walk = np.isin(tiles, list(walkable_ids(rom, hd.tileset)))
    gid = rom[TILESET_TABLE + ENTRY * hd.tileset + 10] if 0 <= hd.tileset < 24 else 0xFF
    g = Grid(walk, tiles == gid if gid != 0xFF else np.zeros_like(walk), {(x, y) for x, y, _w, _m in hd.warps})
    h, w = walk.shape
    pairs = tile_pairs(rom, hd.tileset)
    for y in range(h):
        for x in range(w):
            for name, (dx, dy) in DIRS.items():
                bx, by, cx, cy = x + dx, y + dy, x + 2 * dx, y + 2 * dy
                if not (0 <= bx < w and 0 <= by < h):
                    continue
                if walk[y, x] and walk[by, bx] and pairs and (int(tiles[y, x]), int(tiles[by, bx])) in pairs:
                    g.walls.add((x, y, name))
                if (hd.tileset == 0 and walk[y, x] and not walk[by, bx] and 0 <= cx < w and 0 <= cy < h and walk[cy, cx]
                        and (name, int(tiles[y, x]), int(tiles[by, bx])) in LEDGES):
                    g.jumps[(x, y, name)] = (cx, cy)
    return g


def rom_path(path: str | Path | None = None) -> Path | None:
    """The ROM: ``path``, else the selected game's default ROM in this checkout or under C:/Github/PokeAgent; None if absent."""
    here = Path(__file__).resolve().parents[3]
    for p in ([Path(path)] if path else []) + [default_rom(root=here), default_rom(root=Path("C:/Github/PokeAgent"))]:
        if p.exists():
            return p
    return None


def rom_grids(path: str | Path | None = None):
    """``get(map_id) -> Grid | None`` over the ROM (cached); None when the ROM is absent."""
    p = rom_path(path)
    if p is None:
        return None
    from pokeagent.atlas import rom_maps
    rom = rom_maps.load(p)

    @lru_cache(maxsize=None)
    def get(map_id: int):
        try:
            return from_rom(rom, rom_maps.header(rom, map_id))
        except Exception:  # an unused map id decodes to junk
            return None
    return get
