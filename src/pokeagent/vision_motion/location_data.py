"""Load dataset thumbnails into arrays: (N,72,80) uint8 images, area labels, cells, weights."""
from __future__ import annotations

import numpy as np

WEIGHT_CAP = 20


def parse_cell(cell: str) -> tuple:
    """``"x,y"`` -> ``(x, y)`` for Red tile cells; ``"k"`` -> ``(k,)`` for Mario progress."""
    return tuple(int(p) for p in str(cell).split(","))


def assemble(rows, load) -> dict:
    """``{"rows","images","areas","cells","weights"}`` from thumb rows; ``load(id)`` returns a
    (72, 80) uint8 array. ``cells`` is (N, 2) int64, Mario single cells padded to (k, 0);
    ``weights`` is ``count`` capped at WEIGHT_CAP."""
    images = np.stack([load(r["id"]) for r in rows]) if rows \
        else np.zeros((0, 72, 80), np.uint8)
    cells = np.array([(parse_cell(r["cell"]) + (0, 0))[:2] for r in rows],
                     dtype=np.int64).reshape(-1, 2)
    weights = np.array([min(int(r.get("count", 1)), WEIGHT_CAP) for r in rows],
                       dtype=np.float32)
    return {"rows": rows, "images": images, "areas": [r["area"] for r in rows],
            "cells": cells, "weights": weights}


def load_thumbs(root) -> dict:
    """``assemble`` over a directive-1 dataset root (``runs/vision/<game>``)."""
    from pokeagent.vision.dataset import iter_thumbs, load_thumb

    rows = list(iter_thumbs(root))
    return assemble(rows, lambda i: load_thumb(root, i))
