"""Scan bytes / files against a fingerprint index.

Reports matched windows, coverage of the reference, the longest contiguous matching run (in
target bytes) and the top runs' offsets. PNG inputs are also scanned as decoded raw pixels
(Pillow); every other file type, videos included, is scanned as file bytes only.
A run is consecutive target windows that all hit the index; it does not require the matching
reference offsets to be consecutive too (a conservative over-estimate). Windows dropped as
low-entropy (padding) do not break a run: a gap of up to ``BRIDGE_MAX`` bytes between two hits is
bridged when the reference offsets advance by exactly the same amount as the target offsets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pokeagent.bytecheck.fingerprint import Index
from pokeagent.bytecheck.windows import WINDOW, window_hashes

TOP_RUNS = 5
BRIDGE_MAX = 2 * WINDOW   # widest gap of dropped (padding) windows still bridged, in bytes


@dataclass
class ScanResult:
    path: str
    size: int
    matched_windows: int = 0
    coverage: float = 0.0
    longest_run: int = 0
    top_runs: list[dict] = field(default_factory=list)   # {"offset","length","ref_offset"}
    view: str = "bytes"                                  # which view was worst: bytes|pixels

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def scan_bytes(data: bytes, idx: Index, path: str = "<bytes>") -> ScanResult:
    res = ScanResult(path, len(data))
    hashes, offs = window_hashes(data)
    if not len(hashes):
        return res
    pos = np.searchsorted(idx.hashes, hashes)
    pos[pos == len(idx.hashes)] = 0
    hit = idx.hashes[pos] == hashes if len(idx.hashes) else np.zeros(len(hashes), bool)
    if not hit.any():
        return res
    toffs, pos = offs[hit], pos[hit]
    res.matched_windows = int(hit.sum())
    res.coverage = _coverage(hashes[hit], idx)
    roffs = idx.offsets[pos]
    d, rd = np.diff(toffs), np.diff(roffs)
    join = (d == 1) | ((d <= BRIDGE_MAX) & (rd == d))      # consecutive, or a padded gap with matching ref delta
    brk = np.nonzero(~join)[0] + 1
    first = np.concatenate(([0], brk))
    last = np.concatenate((brk - 1, [len(toffs) - 1]))
    runs = [{"offset": int(toffs[i]), "length": int(toffs[j] - toffs[i]) + WINDOW, "ref_offset": int(roffs[i])}
            for i, j in zip(first, last)]
    runs.sort(key=lambda r: -r["length"])
    res.top_runs, res.longest_run = runs[:TOP_RUNS], runs[0]["length"]
    return res


def _coverage(matched: np.ndarray, idx: Index) -> float:
    """Fraction of reference bytes inside any window whose hash the target matched."""
    sel = np.nonzero(np.isin(idx.hashes, matched))[0]
    diff = np.zeros(idx.ref_size + WINDOW + 1, dtype=np.int32)
    np.add.at(diff, idx.offsets[sel], 1)
    np.add.at(diff, idx.offsets[sel] + WINDOW, -1)
    return float((np.cumsum(diff)[:idx.ref_size] > 0).sum()) / max(idx.ref_size, 1)


def _pixel_bytes(name: str, data: bytes) -> bytes | None:
    if not name.lower().endswith(".png"):
        return None
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.convert("RGBA").tobytes()
    except Exception:
        return None


def scan_file(path: Path, idx: Index) -> ScanResult:
    return scan_blob(Path(path).read_bytes(), idx, str(path))


def scan_blob(data: bytes, idx: Index, path: str) -> ScanResult:
    """Scan already-read content (a file's bytes, or a staged blob); ``path`` names it and picks the PNG pixel view."""
    res = scan_bytes(data, idx, path)
    pix = _pixel_bytes(path, data)
    if pix is not None:
        alt = scan_bytes(pix, idx, path)
        if (alt.longest_run, alt.coverage) > (res.longest_run, res.coverage):
            alt.size, alt.view = res.size, "pixels"
            return alt
    return res
