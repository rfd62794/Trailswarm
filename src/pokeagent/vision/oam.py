"""Game Boy OAM parsing: 160 sprite-attribute bytes into on-screen boxes (generic, any GB game)."""
from __future__ import annotations

SCREEN_W, SCREEN_H = 160, 144
OAM_LEN = 160               # 40 entries of 4 bytes at 0xFE00: (y + 16, x + 8, tile, attr)
LCDC_8X16 = 0x04            # LCDC bit 2: sprites are 8x16 instead of 8x8
ENTRY = 4


def on_screen_boxes(oam: bytes, lcdc: int) -> list[tuple[int, int, int, int, int]]:
    """(index, tile, x, y, h) per on-screen OAM entry. Width is always 8; h is 16 when LCDC bit 2
    is set, else 8. The 16-high tile label has bit 0 cleared (the hardware ignores it there).
    Partially off-screen entries are kept; cropping clips or refuses them, never the parse."""
    h = 16 if lcdc & LCDC_8X16 else 8
    out = []
    for i in range(min(len(oam), OAM_LEN) // ENTRY):
        y, x, tile = oam[ENTRY * i] - 16, oam[ENTRY * i + 1] - 8, oam[ENTRY * i + 2]
        if -h < y < SCREEN_H and -8 < x < SCREEN_W:
            out.append((i, tile & 0xFE if h == 16 else tile, x, y, h))
    return out
