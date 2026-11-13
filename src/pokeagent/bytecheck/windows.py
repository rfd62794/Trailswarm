"""Windowed 64-bit hashing shared by the index builder and the scanner.

Every 32-byte window at stride 1 is hashed with a position-weighted wrapping sum
(``sum((b[k]+1) * M[k]) mod 2**64``, M from splitmix64). Windows without enough entropy are
dropped: fewer than ``MIN_DISTINCT`` distinct byte values, or more than ``MAX_FILL`` bytes that
are 0x00/0xFF. That removes padding runs and repeated tiles, which match everywhere.
"""
from __future__ import annotations

import numpy as np

WINDOW = 32
MIN_DISTINCT = 8
MAX_FILL = 24          # of 32 bytes may be 0x00 / 0xFF
_CHUNK = 1 << 18

_MASK = (1 << 64) - 1


def _splitmix(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & _MASK
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK
    return x ^ (x >> 31)


_MULT = np.array([_splitmix(k) | 1 for k in range(WINDOW)], dtype=np.uint64)


def window_hashes(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """(hashes, offsets) of every entropic window, offsets ascending. Empty if len < WINDOW."""
    arr = np.frombuffer(data, dtype=np.uint8)
    n = len(arr) - WINDOW + 1
    if n <= 0:
        return np.empty(0, np.uint64), np.empty(0, np.int64)
    hs, offs = [], []
    for start in range(0, n, _CHUNK):
        stop = min(n, start + _CHUNK)
        view = np.lib.stride_tricks.sliding_window_view(arr[start:stop + WINDOW - 1], WINDOW)
        keep = _entropic(view)
        h = np.zeros(stop - start, dtype=np.uint64)
        with np.errstate(over="ignore"):
            for k in range(WINDOW):
                h += (arr[start + k:stop + k].astype(np.uint64) + np.uint64(1)) * _MULT[k]
        idx = np.nonzero(keep)[0]
        hs.append(h[idx])
        offs.append(idx.astype(np.int64) + start)
    return np.concatenate(hs), np.concatenate(offs)


def _entropic(view: np.ndarray) -> np.ndarray:
    srt = np.sort(view, axis=1)
    distinct = 1 + (srt[:, 1:] != srt[:, :-1]).sum(axis=1)
    fill = ((view == 0) | (view == 0xFF)).sum(axis=1)
    return (distinct >= MIN_DISTINCT) & (fill <= MAX_FILL)
