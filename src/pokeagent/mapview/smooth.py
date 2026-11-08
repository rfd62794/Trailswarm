"""Eases a displayed point toward its latest target so a 10 Hz position feed looks continuous."""
from __future__ import annotations

import math

SNAP_PX = 96.0         # farther than this (an area change, a respawn) is a jump, not a glide
RATE = 18.0            # 1/s: about 95% of the way there in a sixth of a second


class Smoother:
    def __init__(self) -> None:
        self._at: dict[str, tuple[float, float]] = {}

    def step(self, targets: dict[str, tuple[float, float]], dt: float) -> dict[str, tuple[float, float]]:
        """Each agent's eased point after ``dt`` seconds; agents not in ``targets`` are forgotten."""
        k = 1.0 - math.exp(-RATE * max(0.0, dt))
        out = {}
        for agent, (tx, ty) in targets.items():
            cx, cy = self._at.get(agent, (tx, ty))
            out[agent] = (tx, ty) if math.hypot(tx - cx, ty - cy) > SNAP_PX else (cx + (tx - cx) * k, cy + (ty - cy) * k)
        self._at = out
        return dict(out)
