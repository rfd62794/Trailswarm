"""The unlabeled WRAM gaps: maximal runs of bytes no ram_map entry covers.

Computed from ram_map.json alone (the sym file is gitignored); an entry covers
[addr, addr + size), so ``covered`` is an upper bound where sizes were inferred (the
at-cap count shows how many labels sit at the 256 guess cap with unknown true extent).
Nothing here names a game, an address family beyond WRAM, or a pokered label.
"""
from __future__ import annotations

import re

WRAM_LO, WRAM_HI = 0xC000, 0xDFFF
AT_CAP = 256
UNKNOWN_NAME = re.compile(r"Unused|Unknown|Filler|Padding|Buffer|Scratch|Temp|Tmp", re.IGNORECASE)


def _addr(e: dict) -> int:
    a = e["addr"]
    return int(a, 16) if isinstance(a, str) else a


def wram_gaps(entries: list[dict], lo: int = WRAM_LO, hi: int = WRAM_HI) -> list[tuple[int, int]]:
    """[(addr, length)] maximal runs in [lo, hi] covered by no entry (overlaps merged)."""
    covered = bytearray(hi - lo + 1)
    for e in entries:
        a = _addr(e)
        for i in range(max(a, lo), min(a + e["size"], hi + 1)):
            covered[i - lo] = 1
    gaps, start = [], None
    for i in range(hi - lo + 1):
        if covered[i]:
            if start is not None:
                gaps.append((lo + start, i - start))
                start = None
        elif start is None:
            start = i
    if start is not None:
        gaps.append((lo + start, hi - lo + 1 - start))
    return gaps


def summary(entries: list[dict]) -> dict:
    """{covered, total, unlabeled, gaps, largest [(addr, len) x6], at_cap, unknown_named (count, bytes)}."""
    gs = wram_gaps(entries)
    total = WRAM_HI - WRAM_LO + 1
    unlabeled = sum(n for _, n in gs)
    unknown = [e for e in entries if UNKNOWN_NAME.search(e["name"])]
    return {"covered": total - unlabeled, "total": total, "unlabeled": unlabeled, "gaps": len(gs),
            "largest": sorted(gs, key=lambda g: -g[1])[:6],
            "at_cap": sum(1 for e in entries if e["size"] == AT_CAP),
            "unknown_named": (len(unknown), sum(e["size"] for e in unknown))}
