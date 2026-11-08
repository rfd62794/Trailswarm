"""``main(argv)``: argument parsing, the refresh daemon thread, and ``run`` with the real viewport.

The refresh thread re-reads ``<source>/maps``, ``<source>/ghosts`` and ``<source>/live`` every
``REFRESH_S`` seconds and swaps a new immutable ``Snapshot`` into the holder under a lock; the
UI thread only ever reads the holder. ``run`` is the only piece no test calls.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pokeagent.mapview import playback
from pokeagent.mapview.areas import AreaStore
from pokeagent.mapview.avatars import AvatarCache, AvatarSource, feed
from pokeagent.mapview.ghosts import GhostStore
from pokeagent.mapview.layout import Layout, place
from pokeagent.mapview.live import LiveStore
from pokeagent.mapview.presets import Preset, resolve
from pokeagent.mapview.view import MapWindow
from pokeagent.mapview.walk import LiveTracker

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
    live: dict = field(default_factory=dict)
    preset: Preset = field(default_factory=resolve)
    agent_status: object = None              # a host-supplied snapshot for the status line


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


def snapshot_once(source: Path, areas: AreaStore, ghosts: GhostStore, fps: int = playback.FPS,
                  live: LiveStore | None = None, preset: Preset | None = None) -> tuple[Snapshot, bool]:
    """One poll of the source: re-read areas, ghosts and live; ``changed`` when anything moved."""
    preset = resolve() if preset is None else preset
    changed = areas.refresh(source)
    changed = ghosts.set_area_names([a.name for a in areas.areas]) or changed
    changed = ghosts.refresh(source) or changed
    if live is not None:
        changed = live.refresh(source, time.time()) or changed
    snap = Snapshot(Path(source), Path(source).exists(), tuple(areas.areas), dict(areas.images),
                    place(areas.areas, gap=preset.area_gap_px),
                    playback.tables(ghosts.ghosts, ghosts.area_names, fps),
                    live.positions() if live else {}, preset)
    return snap, changed


def poll_loop(source, holder: Holder, areas: AreaStore, ghosts: GhostStore, live: LiveStore,
              cache: AvatarCache, frame_for, preset: Preset, fps: int, every_s: float,
              stop: threading.Event) -> None:
    """Daemon body: poll, feed the crop cache, swap the holder on change, sleep."""
    track = LiveTracker(preset.walk_frames)
    while not stop.is_set():
        try:
            snap, changed = snapshot_once(source, areas, ghosts, fps, live, preset)
            if frame_for is not None:
                feed(cache, preset, snap.live, frame_for, track)
            if changed:
                holder.set(snap)
        except Exception:
            pass
        stop.wait(every_s)


def run(source, fps: int = playback.FPS, refresh: float = REFRESH_S, game=None, preset=None, genre=None,
        frame_for=None, rom_bytes=None) -> int:
    """The real window: refresh daemon, viewport, render loop. No test calls this."""
    import dearpygui.dearpygui as dpg

    source, preset = Path(source), resolve(game=game, preset=preset, genre=genre)
    areas, ghosts, live = AreaStore(), GhostStore(), LiveStore()
    provider = None
    if preset.avatar == "rom_sprite" and rom_bytes is not None:
        from pokeagent.mapview.avatar_rom import RomAvatars, book_provider
        provider = RomAvatars(book_provider(rom_bytes))
    cache = AvatarCache()
    snap, _ = snapshot_once(source, areas, ghosts, fps, live, preset)
    holder = Holder(snap)
    stop = threading.Event()
    threading.Thread(target=poll_loop, daemon=True, name="mapview-refresh",
                     args=(source, holder, areas, ghosts, live, cache, frame_for, preset,
                           fps, refresh, stop)).start()
    dpg.create_context()
    win = MapWindow(holder.get(), fps=fps, avatars=AvatarSource(cache, preset, provider))
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
    p.add_argument("--fps", type=int, default=playback.FPS,
                   help="frames per second of the source recording 'every' is measured in (default 60)")
    p.add_argument("--refresh", type=float, default=REFRESH_S, help="re-read cadence in seconds (default 2)")
    p.add_argument("--game", help="named game row of the preset table")
    p.add_argument("--preset", help="named view preset (wins over --game)")
    p.add_argument("--genre", help="named genre fallback when --game/--preset are absent")
    a = p.parse_args(argv)
    return run(a.source, fps=a.fps, refresh=a.refresh, game=a.game, preset=a.preset, genre=a.genre)


if __name__ == "__main__":
    sys.exit(main())
