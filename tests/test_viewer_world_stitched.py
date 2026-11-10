"""The stitched World renderer: gap layout + edge lines, click picking, camera target, and the
headless unified window (one selection driving map camera and gameplay panel)."""
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

dpg = pytest.importorskip("dearpygui.dearpygui")

from pokeagent.mapview import pick, playback
from pokeagent.mapview.app import snapshot_once
from pokeagent.mapview.areas import Area, AreaStore
from pokeagent.mapview.compose import compose_base
from pokeagent.mapview.ghosts import GhostStore
from pokeagent.mapview.layout import LABEL_H, locate, place
from pokeagent.mapview.live import LiveStore
from pokeagent.mapview.presets import EDGE_PALETTE, resolve
from pokeagent.viewer import selection as selmod
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.sources import FakeSource
from pokeagent.viewer.stitched_source import StitchedSource
from test_viewer_agents import FRAME, snap

PRESET = "super-mario-land"


def png(path, w, h=12):
    Image.fromarray(np.zeros((h, w), np.uint8), "L").save(path)


def ghost_file(path, run, agent, area, pts):
    path.write_text(json.dumps({"schema": 1, "run": run, "agent": agent, "outcome": "death",
                                "every": 2, "points": [[area, x, y] for x, y in pts]}),
                    encoding="utf-8")


def make_source(tmp_path):
    """Two areas side by side (60x12 and 40x12); ghosts in both."""
    (tmp_path / "maps").mkdir(parents=True)
    (tmp_path / "ghosts").mkdir()
    png(tmp_path / "maps" / "a.png", 60)
    png(tmp_path / "maps" / "b.png", 40)
    (tmp_path / "maps" / "index.json").write_text(json.dumps({"schema": 1, "levels": {
        "a-1": {"width": 60, "height": 12, "seen": 0.5, "file": "a.png"},
        "b-1": {"width": 40, "height": 12, "seen": 0.5, "file": "b.png"}}}), encoding="utf-8")
    ghost_file(tmp_path / "ghosts" / "r1.json", "r1", "g-1", "a-1", [(10 + i, 5) for i in range(6)])
    ghost_file(tmp_path / "ghosts" / "r2.json", "r2", "g-2", "b-1", [(7 + i, 4) for i in range(4)])
    return tmp_path


def live_file(src, agent, x=30, area="a-1"):
    d = src / "live"
    d.mkdir(exist_ok=True)
    (d / f"{agent}.json").write_text(json.dumps(
        {"schema": 1, "agent": agent, "run": "", "area": area, "x": x, "y": 6,
         "screen_x": None, "screen_y": None, "updated_at": time.time()}), encoding="utf-8")


def snap_for(src, preset):
    areas, ghosts, live = AreaStore(), GhostStore(), LiveStore()
    snap, _ = snapshot_once(src, areas, ghosts, playback.FPS, live, preset)
    return snap


def test_layout_uses_the_preset_gap_and_edges(tmp_path):
    src = make_source(tmp_path)
    preset = resolve(game=PRESET)                     # area_gap_px 8, EDGE_PALETTE
    snap = snap_for(src, preset)
    gap = preset.area_gap_px
    assert snap.layout.offsets["a-1"] == (0, LABEL_H)
    assert snap.layout.offsets["b-1"] == (60 + gap, LABEL_H)
    plain = snap_for(src, replace(preset, edge_palette=()))
    base, plain_base = compose_base(snap), compose_base(plain)
    assert base.shape == plain_base.shape and not np.array_equal(base, plain_base)
    off = snap.layout.offsets["a-1"]
    ring = np.frombuffer(bytes.fromhex(EDGE_PALETTE[0].lstrip("#")), np.uint8)[:3]
    assert (base[off[1] - 1, off[0] + 5] == ring).all()      # the gap ring in the area's colour
    assert (plain_base[off[1] - 1, off[0] + 5] != ring).all()


def test_click_hits_ghost_at_gap_shifted_position(tmp_path):
    src = make_source(tmp_path)
    snap = snap_for(src, resolve(game=PRESET))
    frame = playback.positions(snap.tables, 0.0)
    rect = (0, 0, snap.layout.space_w, snap.layout.space_h)
    drawn = pick.heads(frame, snap.tables, snap.layout, rect, 1.0)
    off = snap.layout.offsets["b-1"]
    assert pick.pick_agent(off[0] + 7.0, off[1] + 4.0, drawn) == ("g-2", "ghost")
    assert pick.pick_agent(off[0] + 40.0, off[1] + 4.0, drawn) is None   # past the head's radius


def test_camera_target_equals_layout_locate(tmp_path):
    lay = place([Area("a-1", 60, 12, 0.5, Path("x"))], gap=8)
    sel = selmod.Selection()
    sel.select("a", "live")
    want = locate(lay, "a-1", 10.0, 6.0)
    assert selmod.camera_target(sel, {"a": want}, lambda a: None) == want


def test_unified_window_one_selection(tmp_path):
    """Headless: featured live agent drives map camera AND gameplay panel; ghost pick, Auto, pan."""
    src = make_source(tmp_path)
    live_file(src, "a")
    model = ViewerModel()
    srcs = {i: FakeSource(i, [snap(i)] * 3, [FRAME] * 3) for i in ("a", "b")}
    model.poll(list(srcs.values()))
    model.drain()
    from pokeagent.viewer.ui.window import ViewerWindow
    win = ViewerWindow(model, srcs, stitched=StitchedSource(src, model, resolve(game=PRESET)))
    dpg.create_context()
    try:
        dpg.add_window(tag=win._win)
        win.stitched.build(headless=True)
        win.set_view_mode("world")
        host, view = win.stitched, win.stitched.view
        host.tick()
        # default selection: the live featured agent, on camera and panel alike
        assert (host.sel.agent, host.sel.source, host.sel.is_live) == ("a", "auto", True)
        assert view.selected == ("a", "live")
        ids = model.ids()
        feat = selmod.featured(view._snap.live, ids)
        assert feat == "a"
        assert selmod.gameplay_agent(host.sel, ids, feat) == ("a", "")
        assert selmod.camera_target(view.sel, view._live_points(), view._best_ghost_pos) == \
            view._live_points()["a"] == locate(view.layout, "a-1", 30, 6)
        assert "Selected: a" in win.status_line()
        # a ghost-only pick: camera to the ghost, panel stays on featured with the notice
        host.pick("g-2", "ghost")
        host.tick()
        assert host.sel.agent == "g-2" and view.selected == ("g-2", "ghost")
        target = selmod.camera_target(view.sel, view._live_points(), view._best_ghost_pos)
        assert target is not None and target == view._best_ghost_pos("g-2")
        assert selmod.gameplay_agent(host.sel, ids, feat) == \
            ("a", "g-2: recorded run, no live frames - showing a")
        assert "Selected: g-2" in win.status_line()
        # panning disables follow; a pick re-enables it
        view._user_panned()
        assert not view.follow_best and not view.follow.active
        host.tick()
        assert "Follow: off" in win.status_line()
        host.pick("g-2", "ghost")
        assert view.follow_best
        # Auto restores the featured agent for camera and panel
        host.auto()
        host.tick()
        assert host.sel.agent == "a" and host.sel.source == "auto"
        assert selmod.camera_target(view.sel, view._live_points(), view._best_ghost_pos) == \
            view._live_points()["a"]
        assert selmod.gameplay_agent(host.sel, ids, feat) == ("a", "")
    finally:
        dpg.destroy_context()
