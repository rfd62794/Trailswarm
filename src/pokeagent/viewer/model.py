"""Viewer model: latest snapshot, frame and last-ok time per agent. Thread-safe, copies out.

Pull model: every source kind has its own cadence. Snapshots run at ``SNAPSHOT_HZ_IDLE`` for
unfocused agents and ``SNAPSHOT_HZ_FOCUS`` for the focused one; frames are read only for the
on-screen set the views declare via ``set_wants`` (``visible_frame_set`` on the window). The
worker pool runs only sources DUE this tick; a source still in flight is skipped, not queued,
so a slow agent never piles work up. The render path reads cached state only.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Iterable

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.sources import AgentSource

log = logging.getLogger(__name__)

LIVE_S, LOST_S = 2.0, 10.0
POLL_WORKERS = 8
SNAPSHOT_HZ_IDLE, SNAPSHOT_HZ_FOCUS = 2.0, 10.0   # snapshot cadence: unfocused agents vs the focused one
CARD_FRAME_HZ, FOCUS_FRAME_HZ = 10.0, 30.0      # frame cadence: grid/stadium cards vs the focus view's card
DEAD_AFTER = 5                                  # failed snapshot polls before an agent counts as dead
DEAD_RETRY_S = 2.0                              # untuned: a dead agent is retried at most this often (no frames)
_NEVER = -1e9
_SKIP = object()                                # "not read this call" (distinct from None = read failed)


class ViewerModel:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._snap: dict[str, AgentSnapshot] = {}
        self._frame: dict[str, tuple[bytes, int, int]] = {}
        self._last_ok: dict[str, float] = {}
        self._fails: dict[str, int] = {}
        self._snap_at: dict[str, float] = {}
        self._frame_at: dict[str, float] = {}
        self._inflight: set[str] = set()
        self._futures: set = set()
        self._focused: str | None = None
        self._frame_hz: dict[str, float] = {}
        self._pool = ThreadPoolExecutor(max_workers=POLL_WORKERS, thread_name_prefix="viewer-poll")

    # -- demand declared by the UI thread ----------------------------------------------
    def set_wants(self, focused: str | None = None, frames: dict[str, float] | None = None) -> None:
        """What the views need right now: ``focused`` gets the focus cadences; ``frames`` maps every
        on-screen agent to the frame Hz its card wants (``visible_frame_set`` on the window)."""
        with self._lock:
            self._focused = focused
            if frames is not None:
                self._frame_hz = dict(frames)

    # -- polling ------------------------------------------------------------------------
    def _read_one(self, src: AgentSource, want_snap: bool, want_frame: bool) -> None:
        aid = src.agent_id
        snap, frame = _SKIP, _SKIP
        try:
            if want_snap:
                snap = src.snapshot()
            if want_frame:
                frame = src.frame()
        except Exception:  # sources must not raise; one that does counts as a failed poll, never kills the poller
            log.warning("poll %s failed", aid, exc_info=True)
            snap, frame = (None if want_snap else _SKIP), None
        with self._lock:
            self._inflight.discard(aid)
            self._last_ok.setdefault(aid, float("-inf"))
            if want_snap:
                self._fails[aid] = 0 if snap is not None else self._fails.get(aid, 0) + 1
                if snap is not None:
                    self._snap[aid] = snap
                    self._last_ok[aid] = self._clock()
            if frame is not _SKIP and frame is not None:
                self._frame[aid] = frame

    def _due(self, agent_id: str, now: float) -> tuple[bool, bool]:
        """(snapshot due, frame due) this tick; a dead agent polls at DEAD_RETRY_S and never reads frames."""
        dead = self._fails.get(agent_id, 0) >= DEAD_AFTER
        gap = DEAD_RETRY_S if dead else 1.0 / (
            SNAPSHOT_HZ_FOCUS if agent_id == self._focused else SNAPSHOT_HZ_IDLE)
        snap_due = now - self._snap_at.get(agent_id, _NEVER) >= gap
        frame_hz = 0.0 if dead else self._frame_hz.get(agent_id, 0.0)
        frame_due = frame_hz > 0 and now - self._frame_at.get(agent_id, _NEVER) >= 1.0 / frame_hz
        return snap_due, frame_due

    def poll(self, sources: Iterable[AgentSource]) -> None:
        """Hand each DUE source to the pool and return at once; an in-flight source is skipped,
        not queued. I/O happens outside the lock; a hung agent only ever delays itself."""
        now = self._clock()
        for src in list(sources):
            aid = src.agent_id
            with self._lock:
                if aid in self._inflight:
                    continue
                want_snap, want_frame = self._due(aid, now)
                if not (want_snap or want_frame):
                    continue
                self._inflight.add(aid)
                if want_snap:
                    self._snap_at[aid] = now
                if want_frame:
                    self._frame_at[aid] = now
            f = self._pool.submit(self._read_one, src, want_snap, want_frame)
            with self._lock:
                self._futures.add(f)                # add before the callback: an already-done future
                f.add_done_callback(self._futures.discard)   # still discards itself

    def drain(self) -> None:
        """Block until every submitted read landed (tests and shutdown; the poll loop never calls it)."""
        while True:
            with self._lock:
                pending = [f for f in self._futures if not f.done()]
            if not pending:
                return
            wait(pending)

    # -- reads (render thread; dict lookups only) ---------------------------------------
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
            for d in (self._snap, self._frame, self._last_ok, self._fails,
                      self._snap_at, self._frame_at, self._frame_hz):
                d.pop(agent_id, None)
            self._inflight.discard(agent_id)
            if self._focused == agent_id:
                self._focused = None

    def prune(self, now: float | None = None, after_s: float = 60.0) -> list[str]:
        """Drop agents lost for longer than ``after_s``; returns the dropped ids."""
        now = self._clock() if now is None else now
        with self._lock:
            gone = [i for i, t in self._last_ok.items() if now - t > after_s]
        for i in gone:
            self.forget(i)
        return gone
