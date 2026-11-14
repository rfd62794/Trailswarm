"""visible_cells: full 8x8 cells only, SCX/SCY wrap at 256, the map-select bit, skip_top_px."""
from __future__ import annotations

from pokeagent.vision.bgmap import visible_cells


def bg():
    return bytes(i & 0xFF for i in range(1024))    # tile id = index mod 256, every cell distinct


def cells_by_pos(cells):
    return {(c.x, c.y): c.label for c in cells}


def test_aligned_window_emits_the_20x18_grid():
    cells = visible_cells(bg(), 0, 0)
    at = cells_by_pos(cells)
    assert len(cells) == 20 * 18
    assert at[(0, 0)] == 0 and at[(8, 0)] == 1 and at[(0, 8)] == 32 and at[(152, 136)] == (17 * 32 + 19) & 0xFF


def test_every_cell_is_a_full_8x8_inside_the_screen_for_any_scroll():
    for scx, scy in ((4, 0), (0, 7), (252, 255), (160, 160), (255, 255)):
        for c in visible_cells(bg(), scx, scy):
            assert 0 <= c.x and c.x + 8 <= 160 and 0 <= c.y and c.y + 8 <= 144


def test_scx_scy_wrap_the_256_pixel_map():
    at = cells_by_pos(visible_cells(bg(), 248, 0))            # map x 31 wraps to column 0
    assert at[(0, 0)] == 31 and at[(8, 0)] == 0
    at = cells_by_pos(visible_cells(bg(), 0, 248))            # map y 31 wraps to row 0
    assert at[(0, 0)] == 31 * 32 & 0xFF and at[(0, 8)] == 0
    at = cells_by_pos(visible_cells(bg(), 255, 0))            # half-tile scroll: partial column dropped
    assert min(at) == (1, 0) and at[(1, 0)] == 0


def test_skip_top_px_drops_cells_whose_top_is_above_it():
    cells = visible_cells(bg(), 0, 0, skip_top_px=8)
    assert cells and min(c.y for c in cells) == 8
    assert len(cells) == 20 * 17
