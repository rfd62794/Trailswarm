"""Claude lease: while it is active the agent makes no decisions of its own (exactly like HumanHold).

``grant(seconds)`` (1..600) starts it, a ``source:"claude"`` press refreshes it (``touch``), ``release`` ends it.
The lease is mirrored to ``<run_dir>/claude_hold.json`` (wall-clock ``until``) so the swarm stall watchdog, which only reads
files, can tell a held agent from a dead one (``lease_active``) and leave it alone.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

LEASE_FILE = "claude_hold.json"
MIN_S, MAX_S, TOUCH_FLOOR_S = 1, 600, 3.0
SLACK_S = 5.0  # NTFS mtime can read a hair earlier than the wall clock `until` was computed from
REFRESH_S, STALE_S = 3.0, 20.0  # the agent re-writes the mirror every REFRESH_S while held; older than STALE_S is not trusted


class ClaudeHold:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self.path, self._clock, self._wall = path, clock, wall
        self._secs, self._until = 0.0, None
        self._last = float("-inf")

    def grant(self, seconds: float) -> float:
        self._secs = float(min(MAX_S, max(MIN_S, seconds)))
        self._until = self._clock() + self._secs
        self._mirror()
        return self._secs

    def touch(self) -> None:
        """A Claude press: re-arm the lease for its granted length (at least a few seconds, even with no lease)."""
        self._until = self._clock() + max(self._secs, TOUCH_FLOOR_S)
        self._mirror()

    def remaining(self) -> float:
        return 0.0 if self._until is None else max(0.0, self._until - self._clock())

    def active(self) -> bool:
        return self.remaining() > 0

    def release(self) -> None:
        self._secs, self._until = 0.0, None
        self._mirror()

    def refresh(self) -> None:
        """Called from the agent's own loop: while held, re-write the mirror every few seconds. A hung agent stops doing this,
        and the watchdog then no longer trusts the file (lease_active wants a fresh mtime)."""
        if self.active() and self._clock() - self._last >= REFRESH_S:
            self._mirror()

    def _mirror(self) -> None:
        if self.path is None:
            return
        self._last = self._clock()
        try:
            if self._until is None:
                try:
                    Path(self.path).unlink(missing_ok=True)
                except OSError:
                    Path(self.path).write_text(json.dumps({"until": 0}), encoding="utf-8")  # cannot delete: say "expired"
            else:
                Path(self.path).write_text(json.dumps({"until": self._wall() + self.remaining()}), encoding="utf-8")
        except OSError:
            pass  # the lease still holds in memory; only the watchdog's view of it is lost


def lease_active(run_dir: Path, wall: Callable[[], float] = time.time) -> bool:
    """Is a Claude lease on this run still running? Only a FRESH mirror counts (refreshed within STALE_S, so a hung agent is
    judged again) and an ``until`` more than MAX_S (+ a little slack) past the file's mtime is nonsense and ignored."""
    path = Path(run_dir) / LEASE_FILE
    try:
        until = float(json.loads(path.read_text(encoding="utf-8")).get("until", 0))
        mtime = path.stat().st_mtime
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    now = wall()
    return until > now and until - mtime <= MAX_S + SLACK_S and now - mtime <= STALE_S
