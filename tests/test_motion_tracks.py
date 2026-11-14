"""tracks.py: grouping rows by (run, area, ident) in frame order; collapse/dwell helpers."""
from __future__ import annotations

from pokeagent.vision_motion import synthetic, tracks


def test_groups_by_run_area_ident_in_frame_order():
    rows = [
        {"f": 16, "run": "r1", "area": "map-1", "player": [0, 0],
         "ents": [["slot1", 7, 4, 4, 254], ["slot2", 9, 8, 8, 255]]},
        {"f": 8, "run": "r1", "area": "map-1", "player": [0, 0],
         "ents": [["slot1", 7, 3, 4, 254]]},
        {"f": 24, "run": "r1", "area": "map-2", "player": [0, 0],
         "ents": [["slot1", 7, 9, 9, 255]]},
        {"f": 32, "run": "r2", "area": "map-1", "player": [0, 0],
         "ents": [["slot1", 7, 5, 4, 254]]},
    ]
    got = tracks.tracks_from_rows(rows)
    assert set(got) == {("r1", "map-1", "slot1"), ("r1", "map-1", "slot2"),
                        ("r1", "map-2", "slot1"), ("r2", "map-1", "slot1")}
    t = got[("r1", "map-1", "slot1")]
    assert [r["f"] for r in t] == [8, 16]      # frame order though the rows arrived unsorted
    assert [r["x"] for r in t] == [3, 4]
    assert got[("r1", "map-2", "slot1")][0]["x"] == 9   # same ident, other area: never mixed
    assert got[("r2", "map-1", "slot1")][0]["x"] == 5   # same ident+area, other run: separate


def test_collapse_dwell_positions_distinct_on_a_handmade_track():
    t = tracks.make_track([(1, 1), (1, 1), (1, 2), (1, 2), (1, 2), (1, 1)])
    assert tracks.collapse(t) == [(1, 1, 2), (1, 2, 3), (1, 1, 1)]
    assert [tracks.dwell_at(t, i) for i in range(6)] == [1, 2, 1, 2, 3, 1]
    assert tracks.positions(t)[3] == (1, 2)
    assert tracks.distinct_tiles(t) == {(1, 1), (1, 2)}


def test_to_rows_round_trips_through_tracks_from_rows():
    made = {"slot1": tracks.make_track([(0, 0), (0, 1), (0, 1)], move=254, label=7)}
    rows = synthetic.to_rows(made, run="rr", area="map-9")
    assert rows[1]["ents"] == [["slot1", 7, 0, 1, 254]]
    back = tracks.tracks_from_rows(rows)
    assert [r["y"] for r in back[("rr", "map-9", "slot1")]] == [0, 1, 1]
