from pathlib import Path

from pokeagent.mapview.areas import Area
from pokeagent.mapview.layout import locate, place


def area(name, w, h):
    return Area(name, w, h, 0.5, Path(f"{name}.png"))


def test_place_pinned_offsets_for_fixed_input():
    areas = [area("A", 100, 20), area("B", 200, 40), area("C", 300, 10),
             area("D", 50, 50), area("E", 600, 70)]
    lay = place(areas, max_row_width=500, gap=32, label_h=20)
    assert lay.offsets == {"A": (0, 20), "B": (132, 20), "C": (0, 112),
                           "D": (332, 112), "E": (0, 214)}
    assert (lay.space_w, lay.space_h) == (600, 284)


def test_place_wraps_rows_at_max_row_width():
    lay = place([area("A", 400, 10), area("B", 400, 10)], max_row_width=500, gap=32, label_h=20)
    assert lay.offsets["A"] == (0, 20)
    assert lay.offsets["B"] == (0, 82)                              # row top 62, under the label strip


def test_overwide_area_gets_a_row_to_itself():
    lay = place([area("W", 9000, 10), area("N", 60, 10)], max_row_width=100, gap=32, label_h=20)
    assert lay.offsets == {"W": (0, 20), "N": (0, 82)}


def test_new_area_appends_without_moving_earlier_ones():
    base = [area("A", 100, 20), area("B", 100, 20)]
    one = place(base, max_row_width=500)
    two = place(base + [area("C", 100, 20)], max_row_width=500)
    assert all(two.offsets[k] == v for k, v in one.offsets.items())
    assert two.offsets["C"] == (264, 20)


def test_locate():
    lay = place([area("A", 100, 20)], label_h=20)
    assert locate(lay, "A", 5, 6) == (5, 26)
    assert locate(lay, "nope", 0, 0) is None                        # area not captured yet
