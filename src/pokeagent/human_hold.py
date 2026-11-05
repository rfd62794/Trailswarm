"""Human hold: the agent stops deciding while a human is steering.

Agents call ``touch()`` on every human press, check ``active()`` before each own decision and
skip deciding while it is True (the game keeps running; only the agent's choices pause).
"""
from __future__ import annotations

import time
from typing import Callable


class HumanHold:
    def __init__(self, idle_s: float = 3.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.idle_s = idle_s
        self._clock = clock
        self._until: float | None = None

    def touch(self) -> None:
        self._until = self._clock() + self.idle_s

    def active(self) -> bool:
        return self._until is not None and self._clock() < self._until

    def release(self) -> None:
        self._until = None
