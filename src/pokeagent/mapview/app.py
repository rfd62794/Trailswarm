"""``main(argv)``: argument parsing, the refresh daemon thread, and ``run`` with the real viewport.

The refresh thread re-reads ``<source>/maps`` and ``<source>/ghosts`` every ``REFRESH_S`` seconds
and swaps a new immutable ``Snapshot`` (areas + images + layout + ghost tables) into the holder
under a lock; the UI thread only ever reads the holder, so the shared replay clock stays
consistent and the camera never jumps. ``run`` is the only piece no test calls.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pokeagent.mapview import playback
from pokeagent.mapview.areas import AreaStore
from pokeagent.mapview.ghosts import GhostStore
from pokeagent.mapview.layout import Layout, place
from pokeagent.mapview.playback import FPS
from pokeagent.mapview.view import MapWindow

REFRESH_S = 2.0


@dataclass(frozen=True)
class Snapshot:
    """One immutable view of the source dir passed to the window."""

    source: Path
    found: bool
    areas: tuple
    images: dict
    layout: Layout
    tables: playback.Tables


class Holder:
    """The latest snapshot, swapped whole under a lock; the UI thread only calls ``get``."""

    def __init__(self, snap: Snapshot) -> None:
        self._lock = threading.Lock()
        self._snap = snap

    def get(self) -> Snapshot:
        with self._lock:
            return self._snap

    def set(self, snap: Snapshot) -> None:
        with self._lock:
            self._snap = snap


def snapshot_once(source: Path, areas: AreaStore, ghosts: GhostStore,
                  fps: int = FPS) -> tuple[Snapshot, bool]:
    """One poll of the source: re-read areas and ghosts; ``changed`` when anything moved."""
    changed = areas.refresh(source)
    changed = ghosts.set_area_names([a.name for a in areas.areas]) or changed
    changed = ghosts.refresh(source) or changed
    snap = Snapshot(Path(source), Path(source).exists(), tuple(areas.areas), dict(areas.images),
                    place(areas.areas), playback.tables(ghosts.ghosts, ghosts.area_names, fps))
    return snap, changed


def poll_loop(source, holder: Holder, areas: AreaStore, ghosts: GhostStore,
              fps: int, every_s: float, stop: threading.Event) -> None:
    """Daemon body: poll, swap the holder on change, sleep. A bad cycle never kills the window."""
    while not stop.is_set():
        try:
            snap, changed = snapshot_once(source, areas, ghosts, fps)
            if changed:
                holder.set(snap)
        except Exception:
            pass
        stop.wait(every_s)


def run(source, fps: int = FPS, refresh: float = REFRESH_S) -> int:
    """The real window: refresh daemon, viewport, render loop. No test calls this."""
    import dearpygui.dearpygui as dpg

    source = Path(source)
    areas, ghosts = AreaStore(), GhostStore()
    snap, _ = snapshot_once(source, areas, ghosts, fps)
    holder = Holder(snap)
    stop = threading.Event()
    threading.Thread(target=poll_loop, args=(source, holder, areas, ghosts, fps, refresh, stop),
                     daemon=True, name="mapview-refresh").start()
    dpg.create_context()
    win = MapWindow(holder.get(), fps=fps)
    win.build()
    dpg.create_viewport(title="Map view", width=1200, height=720)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("mapview_root", True)
    win.resize(dpg.get_viewport_client_width(), dpg.get_viewport_client_height())
    dpg.set_viewport_resize_callback(
        lambda *_: win.resize(dpg.get_viewport_client_width(), dpg.get_viewport_client_height()))
    last = time.monotonic()
    try:
        while dpg.is_dearpygui_running():
            now = time.monotonic()
            win.adopt(holder.get())
            win.tick(now - last, now)
            last = now
            dpg.render_dearpygui_frame()
    finally:
        stop.set()
        dpg.destroy_context()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="map_view",
                                description="Every captured area in one space, every ghost replayed together.")
    p.add_argument("source", type=Path, help="run dir holding maps/index.json + images and ghosts/*.json")
    p.add_argument("--fps", type=int, default=FPS,
                   help="frames per second of the source recording 'every' is measured in (default 60)")
    p.add_argument("--refresh", type=float, default=REFRESH_S, help="re-read cadence in seconds (default 2)")
    a = p.parse_args(argv)
    return run(a.source, fps=a.fps, refresh=a.refresh)


if __name__ == "__main__":
    sys.exit(main())
