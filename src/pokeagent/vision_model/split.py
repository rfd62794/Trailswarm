"""Held-out split by whole areas only; a memorised image must not cross sides."""
from __future__ import annotations

import random

import numpy as np


def split_by_area(areas, test_fraction=0.25, seed=0, min_test_areas=2) -> tuple[set, set]:
    """(train areas, test areas): sorted areas shuffled by ``seed``, whole areas moved
    to the test side until it holds ``test_fraction`` of all rows and at least
    ``min_test_areas`` areas. Needs ``min_test_areas + 1`` areas to exist at all."""
    areas = np.asarray(areas)
    distinct = sorted(set(areas.tolist()))
    if len(distinct) < min_test_areas + 1:
        raise ValueError("need at least 3 areas to split by area")
    order = list(distinct)
    random.Random(seed).shuffle(order)
    test, held = set(), 0
    for a in order:
        if len(test) >= min_test_areas and held >= test_fraction * len(areas):
            break
        test.add(a)
        held += int((areas == a).sum())
    return set(distinct) - test, test


def area_indices(areas, chosen: set) -> np.ndarray:
    """Row indices whose area name is in ``chosen``."""
    return np.flatnonzero(np.isin(np.asarray(areas), list(chosen)))


def drop_leaking_test_rows(ds, train_idx, test_idx) -> tuple[np.ndarray, int]:
    """Drop test rows whose image id also sits on the train side: the model could have
    memorised it, so scoring it would flatter every model. Returns (kept, removed)."""
    train_ids = set(np.asarray(ds.ids)[train_idx].tolist())
    keep = np.array([i for i in np.asarray(test_idx) if ds.ids[i] not in train_ids],
                    np.int64)
    return keep, int(len(test_idx) - len(keep))


def assert_disjoint(train_idx, test_idx, ds) -> None:
    """No area and, separately, no image id may occur on both sides of a split."""
    area = np.asarray(ds.area)
    both = set(area[train_idx].tolist()) & set(area[test_idx].tolist())
    assert not both, f"areas on both sides: {sorted(both)}"
    ids = np.asarray(ds.ids)
    both_ids = set(ids[train_idx].tolist()) & set(ids[test_idx].tolist())
    assert not both_ids, f"image ids on both sides: {len(both_ids)}"
