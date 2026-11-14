"""Nearest-thumbnail baseline: the train thumbnail with the smallest pixel MSE."""
from __future__ import annotations

import numpy as np


def nearest(train_images, test_images, chunk: int = 256) -> np.ndarray:
    """Index of the nearest train thumbnail per test thumbnail. Mean squared difference on
    the 80x72 images, vectorised as ``|a|^2 + |b|^2 - 2 a.b`` one chunk at a time."""
    tr = train_images.astype(np.float32).reshape(len(train_images), -1)
    te = test_images.astype(np.float32).reshape(len(test_images), -1)
    tr_sq = (tr ** 2).sum(axis=1)
    out = np.empty(len(te), np.int64)
    for i in range(0, len(te), chunk):
        blk = te[i:i + chunk]
        d = (blk ** 2).sum(axis=1)[:, None] + tr_sq[None, :] - 2.0 * blk @ tr.T
        out[i:i + chunk] = d.argmin(axis=1)
    return out


def predict_cells(train_cells, idx) -> np.ndarray:
    """The cell of each nearest train thumbnail."""
    return np.asarray(train_cells)[np.asarray(idx)]


def cell_error(true_cells, pred_cells) -> tuple:
    """(mean absolute cell error in cells, share within one cell) over (N, 2) cells."""
    err = np.abs(np.asarray(true_cells, float) - np.asarray(pred_cells, float)).sum(axis=1)
    return float(err.mean()), float((err <= 1).mean())


def median_cell_predict(train_areas, train_cells, test_areas) -> np.ndarray:
    """The trivial predictor: the area's median cell."""
    out = np.zeros((len(test_areas), 2), float)
    for i, a in enumerate(test_areas):
        cells = np.asarray(train_cells)[[j for j, t in enumerate(train_areas) if t == a]]
        out[i] = np.median(cells, axis=0) if len(cells) else 0
    return out
