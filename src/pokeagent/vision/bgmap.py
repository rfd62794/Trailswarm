"""The visible background tile cells of a Game Boy frame from its 32x32 tile-id map."""
from __future__ import annotations

from pokeagent.vision.labels import TileCell

MAP_LEN = 1024              # 32x32 tile ids, row major, at 0x9800 or 0x9C00
LCDC_MAP = 0x08             # LCDC bit 3: background map select (0 -> 0x9800, 1 -> 0x9C00)
SCREEN_W, SCREEN_H = 160, 144
TILE = 8
GRID = 32


def visible_cells(bg_map: bytes, scx: int, scy: int, skip_top_px: int = 0) -> list[TileCell]:
    """Every fully on-screen 8x8 cell of the 160x144 window, as TileCell(tile id, x, y).

    The window starts at (scx, scy) inside the 32x32 map and wraps at 256 pixels; 21x19 cells are
    candidates and any cell not fully inside the screen is dropped, so every emitted cell crops a
    full 8x8. Cells whose top sits above ``skip_top_px`` are dropped (a later game's HUD)."""
    out = []
    for cy in range(SCREEN_H // TILE + 1):
        py = cy * TILE - scy % TILE
        if py < skip_top_px or py < 0 or py + TILE > SCREEN_H:
            continue
        for cx in range(SCREEN_W // TILE + 1):
            px = cx * TILE - scx % TILE
            if px < 0 or px + TILE > SCREEN_W:
                continue
            out.append(TileCell(bg_map[((cy + scy // TILE) % GRID) * GRID + (cx + scx // TILE) % GRID], px, py))
    return out
