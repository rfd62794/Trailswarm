"""split_by_area: whole areas only, deterministic, fraction; leaks dropped from test."""
from __future__ import annotations

import numpy as np
import pytest

from pokeagent.vision_model import data, split


def ds_for(areas, ids=None):
    n = len(areas)
    return data.Dataset(
        images=np.zeros((n, 16, 16, 3), np.uint8), label=np.zeros(n, np.int32),
        coarse=np.zeros(n, np.int8), area=np.array(areas),
        kind=np.zeros(n, np.int8), bank=np.full(n, -1, np.int32),
        weight=np.ones(n, np.float32), w=np.full(n, 16, np.int32),
        h=np.full(n, 16, np.int32),
        ids=np.array(ids if ids is not None else [f"id{i}" for i in range(n)]))


def test_deterministic_whole_areas_and_fraction():
    areas = [f"a{i}" for i in range(6) for _ in range(4)]   # 6 areas, 4 rows each
    tr1, te1 = split.split_by_area(areas, seed=1)
    tr2, te2 = split.split_by_area(areas, seed=1)
    assert tr1 == tr2 and te1 == te2
    assert tr1.isdisjoint(te1) and tr1 | te1 == set(areas)
    assert len(te1) >= 2
    assert sum(areas.count(a) for a in te1) >= 0.25 * len(areas)


def test_too_few_areas_raises():
    with pytest.raises(ValueError, match="need at least 3 areas"):
        split.split_by_area(["a", "a", "b", "b"])


def test_leaking_image_id_dropped_from_test():
    areas = ["a0", "a1", "a2", "a3"]
    train_areas, test_areas = split.split_by_area(areas, seed=0)
    pair = (sorted(train_areas)[0], sorted(test_areas)[0])
    ids = ["shared" if a in pair else a for a in areas]
    ds = ds_for(areas, ids)
    tr = split.area_indices(ds.area, train_areas)
    te = split.area_indices(ds.area, test_areas)
    kept, removed = split.drop_leaking_test_rows(ds, tr, te)
    assert removed == 1 and len(kept) == len(te) - 1
    split.assert_disjoint(tr, kept, ds)
    with pytest.raises(AssertionError):
        split.assert_disjoint(tr, te, ds)


def test_assert_disjoint_fails_on_area_overlap():
    ds = ds_for(["a", "b", "c"])
    with pytest.raises(AssertionError):
        split.assert_disjoint(np.array([0]), np.array([0]), ds)
