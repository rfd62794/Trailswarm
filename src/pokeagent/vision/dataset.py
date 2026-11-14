"""Read back a recorded vision dataset; the reader the model directives import."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image


def _iter_jsonl(path: Path) -> Iterator[dict]:
    """One dict per line of a jsonl file; a half-written last line is skipped, not fatal."""
    if not path.is_file():
        return
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            yield json.loads(ln)
        except ValueError:
            return


def load_meta(root) -> dict:
    """The dataset's meta.json as a dict."""
    return json.loads((Path(root) / "meta.json").read_text(encoding="utf-8"))


def iter_samples(root) -> Iterator[dict]:
    """One samples.jsonl row per unique (kind, label, area, image)."""
    yield from _iter_jsonl(Path(root) / "samples.jsonl")


def load_image(root, id: str) -> np.ndarray:
    """The crop with content id ``id`` as an (h, w, 3) uint8 array."""
    path = Path(root) / "images" / id[:2] / f"{id}.png"
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def iter_thumbs(root) -> Iterator[dict]:
    """One thumbs.jsonl row per unique (area, cell, image)."""
    yield from _iter_jsonl(Path(root) / "thumbs.jsonl")


def load_thumb(root, id: str) -> np.ndarray:
    """The thumbnail with content id ``id`` as an (72, 80) uint8 greyscale array."""
    path = Path(root) / "thumbs" / id[:2] / f"{id}.png"
    with Image.open(path) as im:
        return np.asarray(im, dtype=np.uint8)


def iter_positions(root) -> Iterator[dict]:
    """One positions.jsonl row per sampled frame."""
    yield from _iter_jsonl(Path(root) / "positions.jsonl")
