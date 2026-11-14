"""split.py: whole-area track splits, whole-(area, cell) thumbnail splits, determinism."""
from __future__ import annotations

import pytest

from pokeagent.vision_motion import split, synthetic


def test_area_split_is_deterministic_and_holds_out_whole_areas():
    all_t = synthetic.dataset(0, areas=6, per_area=(3, 3, 3))
    tr1, te1 = split.split_tracks_by_area(all_t, seed=7)
    tr2, te2 = split.split_tracks_by_area(all_t, seed=7)
    assert set(tr1) == set(tr2) and set(te1) == set(te2)          # deterministic for a seed
    assert not ({k[1] for k in tr1} & {k[1] for k in te1})       # no area on both sides
    assert len({k[1] for k in te1}) >= 2                         # min_test_areas
    assert len({k[1] for k in tr1}) >= 1
    assert {k[1] for k in tr1} | {k[1] for k in te1} == {k[1] for k in all_t}


def test_area_split_raises_under_three_areas():
    all_t = {("r", "map-1", "slot0"): synthetic.stationary(10),
             ("r", "map-2", "slot0"): synthetic.stationary(10)}
    with pytest.raises(ValueError, match="need at least 3 areas"):
        split.split_tracks_by_area(all_t)


def _thumb_rows():
    rows = []
    for a in range(2):
        for cx in range(3):
            for cy in range(3):
                rows.append({"id": f"a{a}x{cx}y{cy}", "area": f"map-{a}",
                             "cell": f"{cx},{cy}", "pos": [cx * 4, cy * 4], "count": 1})
    return rows


def test_thumbs_split_holds_out_whole_cells_and_drops_shared_ids():
    rows = _thumb_rows()
    tr1, te1 = split.split_thumbs_by_cell(rows, seed=3)
    tr2, te2 = split.split_thumbs_by_cell(rows, seed=3)
    assert [r["id"] for r in tr1] == [r["id"] for r in tr2]      # deterministic
    assert not ({(r["area"], r["cell"]) for r in tr1}
                & {(r["area"], r["cell"]) for r in te1})
    rows2 = [dict(r) for r in rows]
    rows2 += [{"id": "shared-id", "area": "map-0", "cell": "0,0", "pos": [0, 0], "count": 1},
              {"id": "shared-id", "area": "map-1", "cell": "2,2", "pos": [8, 8], "count": 1}]
    exercised = False
    for seed in range(10):                                       # some seed splits the copies
        tr, te = split.split_thumbs_by_cell(rows2, seed=seed)
        tr_ids, te_ids = {r["id"] for r in tr}, {r["id"] for r in te}
        assert all(r["id"] not in tr_ids for r in te)           # shared id dropped from test
        if "shared-id" in tr_ids and "a1x2y2" in te_ids:
            exercised = True                                    # held-out block lost its copy
            assert "shared-id" not in te_ids
    assert exercised
