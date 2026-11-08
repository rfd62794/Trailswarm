"""The fast live-only feed: re-reads just ``<source>/live`` about 10 times a second, off the UI thread.

Positions go straight into the holder (``set_live``) and the crop cache is fed from them, so the
live marker and follow camera do not wait for the slow full poll. Its own ``LiveStore`` keeps the
thread independent of the slow poll's stores.
"""
from __future__ import annotations

import threading
import time

from pokeagent.mapview.avatars import feed
from pokeagent.mapview.live import LiveStore
from pokeagent.mapview.walk import LiveTracker

LIVE_HZ = 10.0


def live_once(source, store: LiveStore, holder, cache, frame_for, preset, track, now: float) -> bool:
    """One fast read; True when the positions changed."""
    changed = store.refresh(source, now)
    pos = store.positions()
    if changed:
        holder.set_live(pos)
    if frame_for is not None and pos:
        feed(cache, preset, pos, frame_for, track)
    return changed


def live_loop(source, holder, cache, frame_for, preset, stop: threading.Event, hz: float = LIVE_HZ) -> None:
    """Daemon body: read live files, publish, sleep; an error never ends the loop."""
    store, track = LiveStore(), LiveTracker(preset.walk_frames)
    while not stop.is_set():
        try:
            live_once(source, store, holder, cache, frame_for, preset, track, time.time())
        except Exception:
            pass
        stop.wait(1.0 / hz)
