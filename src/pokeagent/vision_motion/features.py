"""Track features for the movement classifier; pure numpy, first ``W`` rows only."""
from __future__ import annotations

import numpy as np

W = 24
FEATURE_NAMES = ("distinct", "changed_frac", "bbox_w", "bbox_h", "reversals",
                 "mean_dwell", "collinear")


def reversals(track) -> int:
    """Direction reversals among the track's non-stay sample-to-sample displacements."""
    d = [(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(track, track[1:])]
    nz = [s for s in d if s != (0, 0)]
    return sum(1 for a, b in zip(nz, nz[1:]) if a[0] * b[0] + a[1] * b[1] < 0)


def collinear(track) -> bool:
    """All observed tiles on one row or one column."""
    xs = {r["x"] for r in track}
    ys = {r["y"] for r in track}
    return len(xs) <= 1 or len(ys) <= 1


def features(track, w: int = W) -> np.ndarray:
    """The ``FEATURE_NAMES`` vector computed on the first ``w`` rows of the track."""
    rows = track[:w]
    tiles = {(r["x"], r["y"]) for r in rows}
    changed = sum(1 for a, b in zip(rows, rows[1:]) if (a["x"], a["y"]) != (b["x"], b["y"]))
    xs = [r["x"] for r in rows]
    ys = [r["y"] for r in rows]
    return np.array([
        float(len(tiles)),
        changed / max(len(rows) - 1, 1),
        float(max(xs) - min(xs)),
        float(max(ys) - min(ys)),
        float(reversals(rows)),
        len(rows) / max(len(tiles), 1),
        float(collinear(rows)),
    ])
