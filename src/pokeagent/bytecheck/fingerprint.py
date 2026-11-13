"""Build and load the fingerprint index: sorted 64-bit window hashes + offsets, never bytes.

The index lives in ``runs/bytecheck/`` (gitignored) and is built locally from the reference
binary (the ROM) whose path is given at runtime.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pokeagent.bytecheck.windows import WINDOW, window_hashes

DEFAULT_DIR = Path("runs") / "bytecheck"
DEFAULT_INDEX = DEFAULT_DIR / "index.npz"
FORMAT = 1


class IndexError_(Exception):
    """No usable index (missing or wrong format)."""


@dataclass(frozen=True)
class Index:
    hashes: np.ndarray      # sorted uint64
    offsets: np.ndarray     # int64, reference offset of each hash (parallel to hashes)
    ref_size: int
    ref_sha1: str
    window: int = WINDOW

    @property
    def distinct(self) -> int:
        return len(self.hashes)


def build_index(ref: bytes) -> Index:
    hashes, offsets = window_hashes(ref)
    order = np.argsort(hashes, kind="stable")
    return Index(hashes[order], offsets[order], len(ref), hashlib.sha1(ref).hexdigest())


def save_index(idx: Index, path: Path = DEFAULT_INDEX) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:     # file object: np.savez must not append ".npz"
        np.savez_compressed(f, format=FORMAT, window=idx.window, ref_size=idx.ref_size,
                            ref_sha1=idx.ref_sha1, hashes=idx.hashes, offsets=idx.offsets)
    return path


def load_index(path: Path = DEFAULT_INDEX) -> Index:
    if not Path(path).is_file():
        raise IndexError_(f"no bytecheck index at {path}; build one with "
                          "`pokeagent bytecheck build --ref <path to ROM>`")
    with np.load(path) as z:
        if int(z["format"]) != FORMAT or int(z["window"]) != WINDOW:
            raise IndexError_(f"index {path} has an incompatible format; rebuild it")
        return Index(z["hashes"], z["offsets"], int(z["ref_size"]), str(z["ref_sha1"]))
