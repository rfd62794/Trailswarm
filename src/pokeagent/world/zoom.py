"""Crisp zoom steps for the world view (pure): integer pixel scales of the base tiles, no fractional blur."""
from __future__ import annotations

SNAPS = (0.125, 0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)  # screen px per world px


def step(zoom: float, direction: int, snaps: tuple[float, ...] = SNAPS) -> float:
    """The next snap above (direction > 0) or below the zoom; stays put at the ends."""
    if direction > 0:
        return next((s for s in snaps if s > zoom * 1.001), snaps[-1])
    return next((s for s in reversed(snaps) if s < zoom * 0.999), snaps[0])


def nearest(zoom: float, snaps: tuple[float, ...] = SNAPS) -> float:
    return min(snaps, key=lambda s: abs(s - zoom))


def fit_snap(world_w: float, world_h: float, screen_w: float, screen_h: float,
             snaps: tuple[float, ...] = SNAPS) -> float:
    """Largest snap that shows the whole world; if even the smallest does not fit, the exact fit (so Fit always works)."""
    exact = min(screen_w / world_w, screen_h / world_h)
    fits = [s for s in snaps if s <= exact]
    return fits[-1] if fits else exact
