"""The shared replay clock and every ghost's state at time t (pure numpy).

All ghosts start at t = 0 together regardless of when their attempt happened ("replayed
together"). A ghost's point ``i`` is at time ``i * every / fps`` seconds; normal speed advances
the replay clock 1.0 s per real second. Ghosts of different lengths are padded into 2-D arrays
when the store changes (``tables``), so ``positions`` runs per frame in time proportional to the
ghost count with a small constant and allocates no per-ghost Python objects.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pokeagent.mapview.ghosts import Ghost

FPS = 60                   # frames per second of the source recording ``every`` is measured in
TRAIL_POINTS = 90          # points of trail kept behind each head (~3 s at every=2, fps=60)


@dataclass
class Clock:
    """The one replay clock. ``duration`` is the longest visible ghost's span in seconds; the
    clock loops back to 0 once ``t`` passes it plus ``loop_gap``, restarting all ghosts together."""

    fps: int = FPS
    t: float = 0.0
    speed: float = 1.0
    paused: bool = False
    loop_gap: float = 1.5
    duration: float = 0.0

    def advance(self, dt: float) -> bool:
        """Move ``t`` by ``dt`` real seconds; True when the clock just looped back to 0."""
        if self.paused or dt <= 0:
            return False
        self.t += dt * self.speed
        if self.t > self.duration + self.loop_gap:
            self.t = 0.0
            return True
        return False


@dataclass(frozen=True)
class Tables:
    """Per-ghost data padded to one shape, built when the ghost set changes - never per frame."""

    ghosts: tuple[Ghost, ...]
    area_names: tuple[str, ...]
    runs: tuple[str, ...]
    agents: tuple[str, ...]
    outcomes: tuple[str, ...]
    n: np.ndarray              # int32 per ghost: point count
    area_idx: np.ndarray       # (G, N) int16, padded with -1
    xs: np.ndarray             # (G, N) float32
    ys: np.ndarray             # (G, N) float32
    durations: np.ndarray      # float32 per ghost: time of its last point
    rate: np.ndarray           # float32 per ghost: fps / every


@dataclass(frozen=True)
class Frame:
    """Every ghost's state at time t: point index, area index, (x, y), finished, trail start."""

    idx: np.ndarray            # int32 per ghost
    area: np.ndarray           # int16 per ghost: index into Tables.area_names, -1 unknown
    xs: np.ndarray             # float32
    ys: np.ndarray             # float32
    finished: np.ndarray       # bool: t is past the ghost's last point
    trail_from: np.ndarray     # int32: first trail point index


def tables(ghosts, area_names, fps: int = FPS) -> Tables:
    gs = tuple(ghosts)
    n = np.array([len(g.xs) for g in gs], np.int32)
    width = int(n.max()) if len(n) else 0
    ai = np.full((len(gs), width), -1, np.int16)
    xs = np.zeros((len(gs), width), np.float32)
    ys = np.zeros((len(gs), width), np.float32)
    for k, g in enumerate(gs):
        m = len(g.xs)
        ai[k, :m], xs[k, :m], ys[k, :m] = g.area_idx, g.xs, g.ys
    every = np.array([g.every for g in gs], np.int32)
    durations = np.maximum(n - 1, 0).astype(np.float32) * (every.astype(np.float32) / fps)
    rate = np.where(every > 0, np.float32(fps) / every, np.float32(0)).astype(np.float32)
    return Tables(gs, tuple(area_names), tuple(g.run for g in gs), tuple(g.agent for g in gs),
                  tuple(g.outcome for g in gs), n, ai, xs, ys, durations, rate)


def positions(tb: Tables, t: float) -> Frame:
    """Point ``i = min(n-1, floor(t * fps / every))`` per ghost, its area index and (x, y)."""
    count = len(tb.ghosts)
    if count == 0:
        z = np.zeros(0, np.int32)
        return Frame(z, np.zeros(0, np.int16), np.zeros(0, np.float32),
                     np.zeros(0, np.float32), np.zeros(0, bool), z)
    i = np.clip((t * tb.rate).astype(np.int32), 0, tb.n - 1)
    g = np.arange(count)
    return Frame(i, tb.area_idx[g, i], tb.xs[g, i], tb.ys[g, i],
                 t > tb.durations, np.maximum(0, i - TRAIL_POINTS))
