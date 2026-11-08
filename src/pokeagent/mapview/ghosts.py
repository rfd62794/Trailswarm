"""Read ghost tracks (<source>/ghosts/*.json), tolerantly; cache keyed by file (mtime, size).

One file per attempt: ``{"schema": 1, "run", "agent", "outcome", "every", "points": [[area, x, y]]}``.
A malformed file drops the whole ghost (never a partial one); the writer's next atomic write fixes it.
``area_names`` is kept on the store as one shared order: each ghost point holds its index into it,
or -1 for an area not captured yet - such a ghost is simply not drawn until its area arrives.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Ghost:
    run: str
    agent: str
    outcome: str
    every: int
    area_idx: np.ndarray       # int16 per point: index into the store's area_names, -1 unknown
    xs: np.ndarray             # float32 per point
    ys: np.ndarray             # float32 per point


def _parse(path: Path, names: list[str] | None) -> tuple[Ghost | None, list[str]]:
    """The one parse path: returns (ghost, per-point area names). Ghost is None on any failure."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        return None, []
    run, agent, outcome, every, points = (doc.get(k) for k in ("run", "agent", "outcome", "every", "points"))
    if not all(isinstance(v, str) for v in (run, agent, outcome)):
        return None, []
    if type(every) is not int or every <= 0 or not isinstance(points, list) or not points:
        return None, []
    lookup = {n: i for i, n in enumerate(names)} if names is not None else {}
    n = len(points)
    idx, xs, ys = np.empty(n, np.int16), np.empty(n, np.float32), np.empty(n, np.float32)
    areas: list[str] = []
    for i, p in enumerate(points):
        if not (isinstance(p, (list, tuple)) and len(p) == 3 and isinstance(p[0], str)
                and type(p[1]) in (int, float) and type(p[2]) in (int, float)):
            return None, []
        if names is None and p[0] not in lookup:
            lookup[p[0]] = len(lookup)
        idx[i], xs[i], ys[i] = lookup.get(p[0], -1), float(p[1]), float(p[2])
        areas.append(p[0])
    return Ghost(run, agent, outcome, every, idx, xs, ys), areas


def load_ghost(path, names: list[str] | None = None) -> Ghost | None:
    """Parse one file; ``names`` is the shared area order (a name not in it gets index -1).
    With no ``names`` each point area indexes a fresh first-appearance order. Never raises."""
    return _parse(Path(path), names)[0]


class GhostStore:
    """All ghost files under <source>/ghosts, re-parsing only files whose stamp changed;
    vanished files are forgotten (the writer caps the count and deletes the oldest)."""

    def __init__(self) -> None:
        self.ghosts: list[Ghost] = []
        self.area_names: list[str] = []
        self.parsed = 0                          # total files parsed (tests count re-parses)
        self._files: dict[str, tuple[tuple[int, int], Ghost]] = {}
        self._point_areas: dict[str, list[str]] = {}

    def set_area_names(self, names: list[str]) -> bool:
        """Adopt a new shared area order and re-index every cached ghost from its point names,
        so tracks into newly captured areas appear without re-parsing files."""
        names = list(names)
        if names == self.area_names:
            return False
        self.area_names, lookup = names, {n: i for i, n in enumerate(names)}
        changed = False
        for fname, (stamp, g) in list(self._files.items()):
            idx = np.array([lookup.get(n, -1) for n in self._point_areas[fname]], np.int16)
            if not np.array_equal(idx, g.area_idx):
                self._files[fname] = (stamp, replace(g, area_idx=idx))
                changed = True
        if changed:
            self.ghosts = [rec[1] for _f, rec in sorted(self._files.items())]
        return changed

    def refresh(self, source: Path) -> bool:
        """One stat per file plus a parse of new/changed ones only. True when anything changed."""
        try:
            files = {p.name: p for p in (Path(source) / "ghosts").glob("*.json") if p.is_file()}
        except OSError:
            files = {}
        live: dict[str, tuple[tuple[int, int], Ghost]] = {}
        changed = False
        for fname, path in files.items():
            try:
                s = path.stat()
                stamp = (s.st_mtime_ns, s.st_size)
            except OSError:
                continue
            rec = self._files.get(fname)
            if rec is not None and rec[0] == stamp:
                live[fname] = rec
                continue
            ghost, areas = _parse(path, self.area_names)
            self.parsed += 1
            changed = True
            if ghost is not None:
                live[fname] = (stamp, ghost)
                self._point_areas[fname] = areas
        gone = set(self._files) - set(live)
        for fname in gone:
            self._point_areas.pop(fname, None)
        self._files = live
        if changed or gone:
            self.ghosts = [rec[1] for _f, rec in sorted(live.items())]
        return changed or bool(gone)
