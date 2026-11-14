"""Nearest-template baseline: a class's template is the mean of its train crops."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pokeagent.vision_model.data import KINDS, encode

TILE = KINDS.index("tile")


@dataclass(frozen=True)
class Templates:
    """Per-class mean images plus the columns needed to pick legal candidates."""

    means: np.ndarray    # (K,D) float32 mean image per class id
    present: np.ndarray  # (K,) bool — a class with no train crop gets no template
    kind: np.ndarray     # (K,) int8 index into KINDS
    bank: np.ndarray     # (K,) int32
    coarse: np.ndarray   # (K,) int8 majority coarse of the class's train rows


def fit_templates(ds, idx, table) -> Templates:
    """Mean image per class over rows ``idx``; ``table`` maps row keys to class ids."""
    idx = np.asarray(idx)
    enc = encode(ds.select(idx), table)
    have = enc >= 0
    flat = ds.images[idx][have].reshape(int(have.sum()), -1).astype(np.float32)
    enc = enc[have]
    K = len(table)
    sums = np.zeros((K, flat.shape[1]), np.float64)
    counts = np.zeros(K, np.int64)
    np.add.at(sums, enc, flat)
    np.add.at(counts, enc, 1)
    present = counts > 0
    means = np.zeros((K, flat.shape[1]), np.float32)
    means[present] = (sums[present] / counts[present, None]).astype(np.float32)
    kind = np.full(K, -1, np.int8)
    bank = np.full(K, -1, np.int32)
    for (k, b, _label), cid in table.items():
        kind[cid], bank[cid] = KINDS.index(k), b
    coarse = np.zeros(K, np.int8)
    rows = idx[have]
    for cid in np.unique(enc):
        coarse[cid] = np.bincount(ds.coarse[rows[enc == cid]].astype(np.int64)).argmax()
    return Templates(means, present, kind, bank, coarse)


def predict_templates(t: Templates, images, kind, bank) -> tuple[np.ndarray, np.ndarray]:
    """(class id, coarse id) per crop: smallest squared distance over legal classes -
    same kind; a tile also needs its bank when that bank has templates, else all banks."""
    X = np.asarray(images).reshape(len(images), -1).astype(np.float32)
    d2 = ((X * X).sum(1)[:, None] - 2.0 * X @ t.means.T
          + (t.means * t.means).sum(1)[None, :])
    kind, bank = np.asarray(kind), np.asarray(bank)
    legal = t.present[None, :] & (t.kind[None, :] == kind[:, None])
    tile_banks = set(t.bank[t.present & (t.kind == TILE)].tolist())
    bank_req = (kind == TILE) & np.isin(bank, list(tile_banks))
    legal &= ~bank_req[:, None] | (t.bank[None, :] == bank[:, None])
    best = np.where(legal.any(1), np.argmin(np.where(legal, d2, np.inf), 1), -1)
    coarse = np.where(best >= 0, t.coarse[np.clip(best, 0, None)], -1)
    return best.astype(np.int64), coarse.astype(np.int64)
