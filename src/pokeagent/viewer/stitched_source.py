"""The unified World view's stitched-map source.

Owns the ``<source>`` directory's stores (areas, ghosts, live), the ``Holder`` the map window
adopts each tick, the avatar cache, and the refresh threads that keep them current — the same
``poll_loop``/``live_loop`` the standalone window uses. ``frame_for`` bridges the viewer model's
cached frames into the avatar crop cache (a registry agent's frame, None for ghost-only names).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from pokeagent.mapview import playback
from pokeagent.mapview.app import REFRESH_S, poll_loop, snapshot_once
from pokeagent.mapview.areas import AreaStore
from pokeagent.mapview.avatars import AvatarCache, AvatarSource, feed
from pokeagent.mapview.fast_live import live_loop
from pokeagent.mapview.ghosts import GhostStore
from pokeagent.mapview.holder import Holder
from pokeagent.mapview.live import LiveStore
from pokeagent.mapview.walk import LiveTracker


class StitchedSource:
    """One map source: stores + holder + avatar cache + the two refresh threads."""

    def __init__(self, source, model, preset, fps: int = playback.FPS, refresh: float = REFRESH_S) -> None:
        self.source, self.model, self.preset = Path(source), model, preset
        self.fps, self.refresh = fps, refresh
        self.areas, self.ghosts, self.live = AreaStore(), GhostStore(), LiveStore()
        self.cache = AvatarCache()
        self.avatars = AvatarSource(self.cache, preset)
        self._track = LiveTracker(preset.walk_frames)
        snap, _ = snapshot_once(self.source, self.areas, self.ghosts, fps, self.live, preset)
        self.holder = Holder(snap)
        self.stop = threading.Event()
        self.started = False

    def snapshot(self):
        """The latest immutable Snapshot the map window adopts."""
        return self.holder.get()

    def frame_for(self, agent: str):
        """The viewer model's frame for a registry agent; None for ghost-only names."""
        return self.model.frame(agent) if agent in self.model.ids() else None

    def refresh_once(self) -> bool:
        """One synchronous poll of the source (what the refresh thread does each cycle)."""
        snap, changed = snapshot_once(self.source, self.areas, self.ghosts, self.fps, self.live, self.preset)
        feed(self.cache, self.preset, snap.live, self.frame_for, self._track)
        if changed:
            self.holder.set(snap)
        return changed

    def start(self) -> None:
        """The two refresh daemons: a slow full re-read and the fast live-only feed."""
        self.started = True
        threading.Thread(target=poll_loop, daemon=True, name="stitched-refresh",
                         args=(self.source, self.holder, self.areas, self.ghosts, self.live,
                               self.cache, self.frame_for, self.preset, self.fps,
                               self.refresh, self.stop)).start()
        threading.Thread(target=live_loop, daemon=True, name="stitched-live",
                         args=(self.source, self.holder, self.cache, self.frame_for,
                               self.preset, self.stop)).start()

    def close(self) -> None:
        self.stop.set()
