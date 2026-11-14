"""Honest splits: whole areas for tracks; whole (area, cell) blocks for thumbnails. Pure."""
from __future__ import annotations

import random


def _pick_test(keys, weights: dict, test_fraction: float, seed: int, min_test: int) -> set:
    """Greedy seeded choice of test keys, weighted by row/track count, always leaving at
    least one key on the train side."""
    order = sorted(keys)
    random.Random(seed).shuffle(order)
    total = sum(weights[k] for k in keys)
    chosen, have = set(), 0
    for k in order:
        if len(chosen) >= min_test and have >= total * test_fraction:
            break
        if len(keys) - len(chosen) <= 1:
            break
        chosen.add(k)
        have += weights[k]
    return chosen


def split_tracks_by_area(tracks: dict, test_fraction: float = 0.25, seed: int = 0,
                         min_test_areas: int = 2):
    """``{(run, area, ident): track}`` -> ``(train, test)`` holding out whole areas weighted
    by track count, seeded. Fewer than 3 areas is a hard error, never a random fallback."""
    areas: dict = {}
    for key in tracks:
        areas.setdefault(key[1], []).append(key)
    if len(areas) < 3:
        raise ValueError("need at least 3 areas to split by area")
    weights = {a: len(ks) for a, ks in areas.items()}
    test_areas = _pick_test(areas, weights, test_fraction, seed, min_test_areas)
    train = {k: t for k, t in tracks.items() if k[1] not in test_areas}
    test = {k: t for k, t in tracks.items() if k[1] in test_areas}
    return train, test


def split_thumbs_by_cell(rows, test_fraction: float = 0.25, seed: int = 0):
    """``iter_thumbs`` rows -> ``(train, test)`` holding out whole ``(area, cell)`` blocks,
    so screens near a test position are never in training. Any test thumbnail whose id also
    appears in a train block is removed from the test side."""
    blocks: dict = {}
    for r in rows:
        blocks.setdefault((r["area"], r["cell"]), []).append(r)
    weights = {b: len(v) for b, v in blocks.items()}
    test_blocks = _pick_test(blocks, weights, test_fraction, seed, 1)
    train = [r for b, rs in blocks.items() if b not in test_blocks for r in rs]
    test = [r for b, rs in blocks.items() if b in test_blocks for r in rs]
    train_ids = {r["id"] for r in train}
    test = [r for r in test if r["id"] not in train_ids]
    return train, test
