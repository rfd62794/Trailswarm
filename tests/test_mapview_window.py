import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

dpg = pytest.importorskip("dearpygui.dearpygui")

from pokeagent.mapview import overlay, playback
from pokeagent.mapview.app import Holder, snapshot_once
from pokeagent.mapview.areas import AreaStore
from pokeagent.mapview.ghosts import GhostStore
from pokeagent.mapview.live import LiveStore
from pokeagent.mapview.presets import resolve
from pokeagent.mapview.view import MapWindow


def png(path, w, h=12, seed=0):
    x = (np.arange(w)[None, :] + np.arange(h)[:, None] * 3 + seed) % 200
    Image.fromarray(x.astype(np.uint8), "L").save(path)


def ghost_file(path, run, agent="w-1", outcome="death", n=8, area="a-1"):
    pts = [[area, 10 + i, 5] for i in range(n)]
    path.write_text(json.dumps({"schema": 1, "game": "g", "run": run, "agent": agent,
                                "outcome": outcome, "every": 2, "points": pts}), encoding="utf-8")


def make_source(tmp_path):
    maps, ghosts = tmp_path / "maps", tmp_path / "ghosts"
    maps.mkdir(parents=True)
    ghosts.mkdir()
    png(maps / "a.png", 80)
    (maps / "index.json").write_text(json.dumps(
        {"schema": 1, "levels": {"a-1": {"width": 80, "height": 12, "seen": 0.7, "file": "a.png"}}}),
        encoding="utf-8")
    ghost_file(ghosts / "r1.json", "r1", agent="w-1")
    ghost_file(ghosts / "r2.json", "r2", agent="w-2", outcome="best", n=12)
    return tmp_path


def holder_for(source):
    areas, ghosts = AreaStore(), GhostStore()
    snap, _ = snapshot_once(source, areas, ghosts, playback.FPS)
    return areas, ghosts, Holder(snap)


@pytest.fixture
def ctx():
    dpg.create_context()
    yield
    dpg.destroy_context()


def test_window_builds_headless_base_once_one_overlay_per_tick(tmp_path, ctx):
    areas, ghosts, holder = holder_for(make_source(tmp_path))
    win = MapWindow(holder.get(), headless=True)
    win.build()
    now = time.monotonic()
    for _ in range(3):
        win.tick(1 / 60, now)
        now += 1 / 60
    assert win.base_builds == 1                                       # composed once, not per tick
    assert win.base is not None and win.base.shape == (32, 80, 3)     # label strip + 80x12
    assert win.uploads == 3                                           # one overlay update per tick
    assert win.overlay_img.ndim == 3 and win.overlay_img.shape[2] == 4
    assert [r[0] for r in win.agent_rows] == ["w-1", "w-2"]           # one row per distinct agent


def test_follow_best_moves_the_centre_toward_the_best_ghost(tmp_path, ctx):
    areas, ghosts, holder = holder_for(make_source(tmp_path))
    win = MapWindow(holder.get(), headless=True)
    win.build()
    now = time.monotonic()
    win.tick(1 / 60, now)
    win._set_follow_best(True)
    cx0, cy0 = win.vp.cx, win.vp.cy
    for i in range(1, 40):
        win.tick(1 / 60, now + i / 60)
    k = win.best
    assert k is not None
    off = win.layout.offsets["a-1"]
    target = (off[0] + float(win.frame.xs[k]), off[1] + float(win.frame.ys[k]))
    before = abs(target[0] - cx0) + abs(target[1] - cy0)
    after = abs(target[0] - win.vp.cx) + abs(target[1] - win.vp.cy)
    assert after < before                                             # the camera eased onto it


def test_empty_source_opens_with_the_waiting_message(tmp_path, ctx):
    areas, ghosts, holder = holder_for(tmp_path / "nope")
    win = MapWindow(holder.get(), headless=True)
    win.build()
    win.tick(1 / 60, time.monotonic())
    assert "waiting for" in win.status and "nope" in win.status
    assert win.base is None


def test_refresh_brings_new_ghost_and_wider_area_without_camera_jump(tmp_path, ctx):
    src = make_source(tmp_path)
    areas, ghosts, holder = holder_for(src)
    win = MapWindow(holder.get(), headless=True)
    win.build()
    win.tick(1 / 60, time.monotonic())
    win.vp.cx, win.vp.cy, win.vp.zoom = 30.0, 18.0, 0.5
    ghost_file(src / "ghosts" / "r3.json", "r3", agent="w-3")
    (src / "ghosts" / "r4.json").write_text('{"schema": 1, "run"')    # a half-written file
    victim = src / "maps" / "a.png"
    png(victim, 160)
    os.utime(victim, (1_900_000_000, 1_900_000_000))
    snap, changed = snapshot_once(src, areas, ghosts, playback.FPS)   # the one refresh call
    assert changed
    assert {g.run for g in snap.tables.ghosts} == {"r1", "r2", "r3"}  # truncated r4 ignored
    assert snap.areas[0].width == 160
    holder.set(snap)
    win.adopt(holder.get())
    assert win.base_builds == 2 and win.base.shape == (32, 160, 3)
    assert (win.vp.cx, win.vp.cy, win.vp.zoom) == (30.0, 18.0, 0.5)   # the camera did not jump
    win.tick(1 / 60, time.monotonic())
    assert "r3" not in win.tables.runs                                # new ghosts wait for loop start
    arrived = False
    for i in range(300):
        if "r3" in win.tables.runs:
            arrived = True
            break
        win.tick(1 / 60, time.monotonic())
    assert arrived


def test_pan_turns_follow_best_off_and_it_stays_off(tmp_path, ctx):
    areas, ghosts, holder = holder_for(make_source(tmp_path))
    win = MapWindow(holder.get(), headless=True)
    win.build()
    now = time.monotonic()
    win.tick(1 / 60, now)
    win._set_follow_best(True)
    win.tick(1 / 60, now + 0.02)
    assert win.follow.active
    win._user_panned()
    assert not win.follow_best and not win.follow.active
    for i in range(3, 10):
        win.tick(1 / 60, now + i / 60)
    assert not win.follow.active                                      # no snap-back


def test_seen_only_change_does_not_rebuild_the_base(tmp_path, ctx):
    import dataclasses
    areas, ghosts, holder = holder_for(make_source(tmp_path))
    win = MapWindow(holder.get(), headless=True)
    snap = holder.get()
    again = dataclasses.replace(snap, areas=tuple(dataclasses.replace(a, seen=0.99) for a in snap.areas))
    win.adopt(again)
    assert win.base_builds == 1


def live_file(source, agent="w-live", x=30, y=6):
    d = source / "live"
    d.mkdir(exist_ok=True)
    rec = {"schema": 1, "agent": agent, "run": "", "area": "a-1", "x": x, "y": y,
           "screen_x": None, "screen_y": None, "updated_at": time.time()}
    (d / f"{agent}.json").write_text(json.dumps(rec), encoding="utf-8")


def live_holder(source, preset=None):
    areas, ghosts, store = AreaStore(), GhostStore(), LiveStore()
    snap, _ = snapshot_once(source, areas, ghosts, playback.FPS, store, preset)
    return areas, ghosts, store, Holder(snap)


def test_follow_live_moves_the_centre_and_draws_the_live_agent(tmp_path, ctx):
    src = make_source(tmp_path)
    live_file(src)
    areas, ghosts, store, holder = live_holder(src)
    win = MapWindow(holder.get(), headless=True)
    win.build()
    assert win.follow_live and win.follow_best                     # follow live is the preset default
    now = time.monotonic()
    win.tick(1 / 60, now)
    pt = win._live_pts["w-live"]
    before = abs(pt[0] - win.vp.cx) + abs(pt[1] - win.vp.cy)
    for i in range(1, 40):
        win.tick(1 / 60, now + i / 60)
    after = abs(pt[0] - win.vp.cx) + abs(pt[1] - win.vp.cy)
    assert after < before                                          # the camera eased onto the live agent
    rgb = overlay.PALETTE[overlay.color_index("w-live", len(overlay.PALETTE))]
    assert (win.overlay_img[..., :3] == rgb).all(-1).any()         # the live agent is in the overlay
    assert (win.overlay_img[..., :3] == [255, 255, 255]).all(-1).any()  # its white ring


def test_no_live_file_falls_back_to_the_best_ghost(tmp_path, ctx):
    areas, ghosts, store, holder = live_holder(make_source(tmp_path))
    win = MapWindow(holder.get(), headless=True)
    win.build()
    assert win.follow_live and not win.follow_best                 # preference on, nothing to follow yet
    win._set_follow_best(True)
    win.tick(1 / 60, time.monotonic())
    assert win.follow.agent_id in win.tables.runs                  # following a ghost, not a live agent


def test_unknown_preset_marks_the_note(tmp_path, ctx):
    areas, ghosts, store, holder = live_holder(make_source(tmp_path), resolve(game="wat"))
    win = MapWindow(holder.get(), headless=True)
    assert win.preset_note == "unknown preset" and win.preset.name == "wat?"


def test_new_live_file_changes_snapshot_without_camera_jump(tmp_path, ctx):
    src = make_source(tmp_path)
    areas, ghosts, store, holder = live_holder(src)
    win = MapWindow(holder.get(), headless=True)
    win.build()
    win._set_follow_best(False)                                    # follow off: no auto re-enable
    win.vp.cx, win.vp.cy = 30.0, 18.0
    live_file(src)
    snap, changed = snapshot_once(src, areas, ghosts, playback.FPS, store)
    assert changed and "w-live" in snap.live
    holder.set(snap)
    win.adopt(holder.get())
    win.tick(1 / 60, time.monotonic())
    assert not win.follow.active                                   # follow stayed off
    assert (win.vp.cx, win.vp.cy) == (30.0, 18.0)                  # the camera did not jump
