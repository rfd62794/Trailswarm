"""Viewer model: latest snapshot, frame and last-ok time per agent. Thread-safe, copies out."""
from __future__ import annotations

import copy
import threading
import time
from typing import Callable, Iterable

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.sources import AgentSource

LIVE_S, LOST_S = 2.0, 10.0


class ViewerModel:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._snap: dict[str, AgentSnapshot] = {}
        self._frame: dict[str, tuple[bytes, int, int]] = {}
        self._last_ok: dict[str, float] = {}

    def poll(self, sources: Iterable[AgentSource]) -> None:
        """Read each source once (called from the background thread); I/O happens outside the lock."""
        for src in sources:
            snap, frame = src.snapshot(), src.frame()
            with self._lock:
                self._last_ok.setdefault(src.agent_id, float("-inf"))
                if snap is not None:
                    self._snap[src.agent_id] = snap
                    self._last_ok[src.agent_id] = self._clock()
                if frame is not None:
                    self._frame[src.agent_id] = frame

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._last_ok)

    def snapshot(self, agent_id: str) -> AgentSnapshot | None:
        with self._lock:
            s = self._snap.get(agent_id)
            return copy.deepcopy(s) if s is not None else None

    def frame(self, agent_id: str) -> tuple[bytes, int, int] | None:
        with self._lock:
            return self._frame.get(agent_id)  # bytes are immutable

    def staleness(self, agent_id: str, now: float | None = None) -> str:
        now = self._clock() if now is None else now
        with self._lock:
            age = now - self._last_ok.get(agent_id, float("-inf"))
        return "live" if age < LIVE_S else "stale" if age <= LOST_S else "lost"

    def forget(self, agent_id: str) -> None:
        with self._lock:
            for d in (self._snap, self._frame, self._last_ok):
                d.pop(agent_id, None)

    def prune(self, now: float | None = None, after_s: float = 60.0) -> list[str]:
        """Drop agents lost for longer than ``after_s``; returns the dropped ids."""
        now = self._clock() if now is None else now
        with self._lock:
            gone = [i for i, t in self._last_ok.items() if now - t > after_s]
        for i in gone:
            self.forget(i)
        return gone
