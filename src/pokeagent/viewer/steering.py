"""Pure steering rules: keys steer only the focused agent, at most one press per key per 120 ms."""
from __future__ import annotations

import time
from typing import Callable

from pokeagent.viewer.commands import press_for_key

KEY_REPEAT_S = 0.12


class KeyThrottle:
    """Drops key-repeat floods: ``allow(key)`` is True at most once per ``min_s`` per key."""

    def __init__(self, min_s: float = KEY_REPEAT_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.min_s, self._clock = min_s, clock
        self._last: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self.min_s:
            return False
        self._last[key] = now
        return True


def press_target(key: str, focused: str | None, throttle: KeyThrottle) -> tuple[str, str] | None:
    """(agent_id, button) to press for ``key``, or None (grid view, unmapped key, throttled)."""
    button = press_for_key(key, focused is not None)
    if button is None or focused is None or not throttle.allow(key):
        return None
    return focused, button


class PressGate:
    """One action per physical key press: a held key emits events every frame, each resetting
    the gap, so only an event after ``gap_s`` of silence counts as a new press."""

    def __init__(self, gap_s: float = 0.3, clock: Callable[[], float] = time.monotonic) -> None:
        self.gap_s, self._clock = gap_s, clock
        self._last: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        last = self._last.get(key)
        self._last[key] = now
        return last is None or now - last > self.gap_s
