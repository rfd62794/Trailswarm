"""on_screen_boxes: 8x8 and 8x16 sprite modes, partial vs fully off-screen entries, label masking."""
from __future__ import annotations

from pokeagent.vision.oam import on_screen_boxes

LCDC_8X16 = 0x04


def oam(entries):
    """{index: (y, x, tile)} in screen coords -> the 160 OAM bytes ((y+16, x+8, tile, attr))."""
    buf = bytearray(160)
    for i, (y, x, tile) in entries.items():
        buf[4 * i], buf[4 * i + 1], buf[4 * i + 2] = (y + 16) & 0xFF, (x + 8) & 0xFF, tile
    return bytes(buf)


def test_8x8_mode_on_screen_and_off_screen():
    boxes = on_screen_boxes(oam({0: (0, 0, 0x42), 1: (100, 80, 0x10), 2: (144, 0, 0x99),
                                 3: (0, 160, 0x99)}), 0)
    assert boxes == [(0, 0x42, 0, 0, 8), (1, 0x10, 80, 100, 8)]


def test_partially_off_screen_kept_fully_off_dropped():
    boxes = on_screen_boxes(oam({0: (-4, -4, 1), 1: (-8, 0, 2), 2: (0, -8, 3), 3: (143, 159, 4)}), 0)
    assert boxes == [(0, 1, -4, -4, 8), (3, 4, 159, 143, 8)]


def test_8x16_mode_height_edges_and_label_mask():
    boxes = on_screen_boxes(oam({0: (-15, 0, 0x43), 1: (-16, 0, 0x45), 2: (0, 0, 0x42)}), LCDC_8X16)
    assert boxes == [(0, 0x42, 0, -15, 16), (2, 0x42, 0, 0, 16)]   # bit 0 cleared when h == 16


def test_short_oam_reads_only_whole_entries():
    assert on_screen_boxes(oam({0: (0, 0, 7)})[:4], 0) == [(0, 7, 0, 0, 8)]
