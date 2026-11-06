"""Viewer limits: at most VIEW_MAX cards on screen (the rest cycle through as pages) and a spawn-button guard."""
from __future__ import annotations

import os
import time
from typing import Callable

VIEW_MAX = 8
VIEW_MIN, VIEW_CEIL = 6, 12
SPAWN_DEBOUNCE_S = 2.0


def clamp_view_max(v) -> int:
    try:
        return max(VIEW_MIN, min(VIEW_CEIL, int(v)))
    except (TypeError, ValueError):
        return VIEW_MAX


def view_max() -> int:
    """Configured card limit (env POKEAGENT_VIEW_MAX), clamped to 6..12, default 8."""
    return clamp_view_max(os.environ.get("POKEAGENT_VIEW_MAX", VIEW_MAX))


def page_ids(ids: list[str], limit: int, page: int) -> tuple[list[str], int, int]:
    """(visible ids, how many agents are NOT shown, normalised page). ``ids`` come ranked most-active first;
    page 0 is the top ``limit``, later pages cycle through the rest, wrapping back to 0."""
    if len(ids) <= limit:
        return list(ids), 0, 0
    pages = -(-len(ids) // limit)
    page %= pages
    vis = ids[page * limit:(page + 1) * limit]
    return vis, len(ids) - len(vis), page


class SpawnGuard:
    """One spawn in flight, and a 2 s debounce so a repeated GUI callback cannot spawn twice."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, debounce_s: float = SPAWN_DEBOUNCE_S) -> None:
        self._clock, self._debounce = clock, debounce_s
        self._busy = False
        self._last = float("-inf")

    def begin(self) -> bool:
        now = self._clock()
        if self._busy or now - self._last < self._debounce:
            return False
        self._busy, self._last = True, now
        return True

    def end(self) -> None:
        self._busy = False
