"""The stacked-areas gap: neighbour-distinct edge colours, gap in the layout, ring pixels."""
from pathlib import Path

import numpy as np

from pokeagent.mapview.areas import Area
from pokeagent.mapview.edges import draw_edges, edge_colours
from pokeagent.mapview.layout import locate, place

PAL = ("#111111", "#222222", "#333333", "#444444")


def area(name, w, h):
    return Area(name, w, h, 0.5, Path(f"{name}.png"))


def grid(cols, rows, pitch=20, size=10):
    return [(f"a{r * cols + c}", c * pitch, r * pitch, size, size)
            for r in range(rows) for c in range(cols)]


def test_index_and_vertical_neighbours_differ():
    rows = grid(2, 2)
    c = edge_colours(rows, PAL)
    assert c["a0"] != c["a1"] and c["a2"] != c["a3"]          # index neighbours
    assert c["a0"] != c["a2"] and c["a1"] != c["a3"]          # directly above/below


def test_more_areas_than_colours_keeps_neighbours_distinct():
    rows = grid(3, 3)
    c = edge_colours(rows, PAL)
    for i in range(8):
        assert c[f"a{i}"] != c[f"a{i + 1}"], i               # index neighbours
    for i in range(6):
        assert c[f"a{i}"] != c[f"a{i + 3}"], i               # vertical neighbours


def test_two_colour_palette_still_splits_index_neighbours():
    rows = grid(3, 1)
    c = edge_colours(rows, ("#aaaaaa", "#bbbbbb"))
    for i in range(2):
        assert c[f"a{i}"] != c[f"a{i + 1}"]


def test_place_gap_offsets_and_locate():
    lay = place([area("A", 100, 20), area("B", 100, 20)], max_row_width=500, gap=8, label_h=20)
    assert lay.offsets["A"] == (0, 20) and lay.offsets["B"] == (108, 20)
    assert locate(lay, "B", 1, 1) == (109, 21)


def test_draw_edges_colours_only_the_gap_ring():
    base = np.full((50, 100, 3), 255, np.uint8)
    rows = [("a", 10, 10, 20, 10)]
    draw_edges(base, rows, {"a": "#ff0000"}, width=2)
    red = np.array([255, 0, 0], np.uint8)
    assert (base[8, 10] == red).all() and (base[21, 10] == red).all()     # top/bottom of the ring
    assert (base[10, 8] == red).all() and (base[10, 31] == red).all()     # left/right of the ring
    assert (base[10, 10] == 255).all() and (base[15, 19] == 255).all()    # image pixels untouched
    assert (base[6, 10] == 255).all() and (base[10, 33] == 255).all()     # outside the ring untouched


def test_gap_zero_draws_nothing():
    base = np.full((50, 100, 3), 255, np.uint8)
    draw_edges(base, [("a", 10, 10, 20, 10)], {}, width=2)
    assert (base == 255).all()
