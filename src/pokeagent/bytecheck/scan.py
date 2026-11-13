"""Scan bytes / files against a fingerprint index.

Reports matched windows, coverage of the reference, the longest contiguous matching run (in
target bytes) and the top runs' offsets. PNG inputs are also scanned as decoded raw pixels
(Pillow); every other file type, videos included, is scanned as file bytes only.
A run is consecutive target windows that all hit the index; it does not require the matching
reference offsets to be consecutive too (a conservative over-estimate).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pokeagent.bytecheck.fingerprint import Index
from pokeagent.bytecheck.windows import WINDOW, window_hashes

TOP_RUNS = 5


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
    brk = np.nonzero(np.diff(toffs) != 1)[0] + 1
    starts = np.split(toffs, brk)
    runs = [{"offset": int(s[0]), "length": int(len(s)) + WINDOW - 1} for s in starts]
    first = np.concatenate(([0], brk))
    for r, i in zip(runs, first):
        r["ref_offset"] = int(idx.offsets[pos[i]])
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


def _pixel_bytes(path: Path) -> bytes | None:
    if path.suffix.lower() != ".png":
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.convert("RGBA").tobytes()
    except Exception:
        return None


def scan_file(path: Path, idx: Index) -> ScanResult:
    data = Path(path).read_bytes()
    res = scan_bytes(data, idx, str(path))
    pix = _pixel_bytes(Path(path))
    if pix is not None:
        alt = scan_bytes(pix, idx, str(path))
        if (alt.longest_run, alt.coverage) > (res.longest_run, res.coverage):
            alt.size, alt.view = res.size, "pixels"
            return alt
    return res
