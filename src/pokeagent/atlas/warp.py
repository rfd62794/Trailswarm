"""A piecewise-linear stretch of the outdoor world (pure, cells).

Each axis inserts ``extra`` copies of one logical cell column/row at chosen positions; everything after shifts out. The
mapping is strictly increasing (so maps stay contiguous and connection edges stay aligned: every map shares the one axis
warp) and invertible (click-to-tile). Inside an inserted band the position is linear, so a continuous cell coordinate maps
to a continuous one. ``resample`` builds the stretched image by repeating those source cells (a lawn simply gets longer).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np

from pokeagent.atlas.world import CELL


@dataclass(frozen=True)
class AxisWarp:
    inserts: tuple[tuple[int, int], ...] = ()          # (logical cell, extra copies), sorted, unique cell, extra > 0

    def _before(self) -> list[int]:
        out, acc = [], 0
        for _p, e in self.inserts:
            out.append(acc)
            acc += e
        return out

    @property
    def total(self) -> int:
        return sum(e for _p, e in self.inserts)

    def fwd(self, c: float) -> float:
        """Stretched coordinate of logical cell coordinate ``c`` (cell top-left; fractional inside a cell is linear)."""
        pos = [p for p, _ in self.inserts]
        i = bisect.bisect_right(pos, int(np.floor(c))) - 1
        if i < 0:
            return float(c)
        before, (p, e) = self._before()[i], self.inserts[i]
        if c < p + 1:
            return before + p + (c - p) * (1 + e)
        return c + before + e

    def inv(self, u: float) -> float:
        """Logical coordinate of stretched coordinate ``u`` (the inverse of ``fwd``)."""
        before = self._before()
        for (p, e), b in zip(reversed(self.inserts), reversed(before)):
            if u >= p + b:
                return p + (u - p - b) / (1 + e) if u < p + b + 1 + e else u - b - e
        return float(u)

    def source(self, n: int) -> np.ndarray:
        """Logical cell feeding each of the ``n + total`` stretched cells."""
        extra = dict(self.inserts)
        return np.repeat(np.arange(n), [1 + extra.get(i, 0) for i in range(n)])


@dataclass(frozen=True)
class Warp:
    x: AxisWarp = AxisWarp()
    y: AxisWarp = AxisWarp()
    dx: int = 0                  # plain translation of the result (crops)
    dy: int = 0

    def cell(self, cx: float, cy: float) -> tuple[float, float]:
        return self.x.fwd(cx) + self.dx, self.y.fwd(cy) + self.dy

    def uncell(self, ux: float, uy: float) -> tuple[float, float]:
        return self.x.inv(ux - self.dx), self.y.inv(uy - self.dy)


def merge_inserts(*groups: dict[int, int]) -> tuple[tuple[int, int], ...]:
    """Sum per-cell extras from several sources into a sorted inserts tuple."""
    acc: dict[int, int] = {}
    for g in groups:
        for p, e in g.items():
            acc[p] = acc.get(p, 0) + int(e)
    return tuple(sorted((p, e) for p, e in acc.items() if e > 0))


def resample(img: np.ndarray, warp: Warp, rows: int) -> np.ndarray:
    """The first ``rows`` cell rows of ``img`` stretched by ``warp``; the width grows by the x inserts."""
    ncx = img.shape[1] // CELL
    ix = (warp.x.source(ncx)[:, None] * CELL + np.arange(CELL)).ravel()
    iy = (warp.y.source(rows)[:, None] * CELL + np.arange(CELL)).ravel()
    return img[iy][:, ix]
