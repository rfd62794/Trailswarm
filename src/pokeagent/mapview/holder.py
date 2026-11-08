"""The immutable ``Snapshot`` and the lock-guarded ``Holder`` the UI thread reads."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from pokeagent.mapview import playback
from pokeagent.mapview.layout import Layout
from pokeagent.mapview.presets import Preset, resolve


@dataclass(frozen=True)
class Snapshot:
    """One immutable view of the source dir passed to the window."""

    source: Path
    found: bool
    areas: tuple
    images: dict
    layout: Layout
    tables: playback.Tables
    live: dict = field(default_factory=dict)
    preset: Preset = field(default_factory=resolve)
    agent_status: object = None              # a host-supplied snapshot for the status line


class Holder:
    """The latest snapshot, swapped whole under a lock; the UI thread only calls ``get``.
    ``set_live`` swaps just the live positions (the fast feed); a later ``set`` keeps the newest ones."""

    def __init__(self, snap: Snapshot) -> None:
        self._lock = threading.Lock()
        self._snap, self._live = snap, None

    def get(self) -> Snapshot:
        with self._lock:
            return self._snap

    def set(self, snap: Snapshot) -> None:
        with self._lock:
            self._snap = snap if self._live is None else replace(snap, live=self._live)

    def set_live(self, live: dict) -> None:
        with self._lock:
            self._live, self._snap = live, replace(self._snap, live=live)
