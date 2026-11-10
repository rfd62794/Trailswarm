"""StitchedSource: refresh picks up live+ghost changes, frame_for bridges viewer frames."""
import json
import time

import numpy as np
import pytest
from PIL import Image

from pokeagent.mapview.presets import resolve
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.sources import FakeSource
from pokeagent.viewer.stitched_source import StitchedSource
from test_viewer_agents import FRAME, snap

PRESET = "super-mario-land"


def png(path, w, h=12):
    Image.fromarray(np.zeros((h, w), np.uint8), "L").save(path)


def ghost_file(path, run, agent, area="a-1", n=6):
    path.write_text(json.dumps({"schema": 1, "run": run, "agent": agent, "outcome": "death",
                                "every": 2, "points": [[area, 10 + i, 5] for i in range(n)]}),
                    encoding="utf-8")


def make_source(tmp_path):
    (tmp_path / "maps").mkdir(parents=True)
    (tmp_path / "ghosts").mkdir()
    png(tmp_path / "maps" / "a.png", 80)
    (tmp_path / "maps" / "index.json").write_text(json.dumps(
        {"schema": 1, "levels": {"a-1": {"width": 80, "height": 12, "seen": 0.5, "file": "a.png"}}}),
        encoding="utf-8")
    ghost_file(tmp_path / "ghosts" / "r1.json", "r1", "g-1")
    return tmp_path


def live_file(src, agent, x=30, at=None):
    d = src / "live"
    d.mkdir(exist_ok=True)
    rec = {"schema": 1, "agent": agent, "run": "", "area": "a-1", "x": x, "y": 6,
           "screen_x": None, "screen_y": None, "updated_at": time.time() if at is None else at}
    (d / f"{agent}.json").write_text(json.dumps(rec), encoding="utf-8")


@pytest.fixture
def model():
    m = ViewerModel()
    srcs = [FakeSource("a", [snap("a")], [FRAME]), FakeSource("b", [snap("b")], [FRAME])]
    m.set_wants(frames={"a": 10.0, "b": 10.0})        # the window declares frame wants; so do we
    m.poll(srcs)
    m.drain()
    return m


def test_refresh_picks_up_new_live_and_ghost(tmp_path, model):
    src = make_source(tmp_path)
    st = StitchedSource(src, model, resolve(game=PRESET))
    assert "a" not in st.snapshot().live
    live_file(src, "a")
    ghost_file(src / "ghosts" / "r2.json", "r2", "g-2", n=4)
    (src / "ghosts" / "bad.json").write_text('{"schema": 1, "run"')      # truncated: ignored
    assert st.refresh_once()
    snap = st.snapshot()
    assert "a" in snap.live and snap.live["a"].x == 30
    assert {g.run for g in snap.tables.ghosts} == {"r1", "r2"}


def test_stale_live_file_counts_as_absent(tmp_path, model):
    src = make_source(tmp_path)
    live_file(src, "a", at=time.time() - 100)
    st = StitchedSource(src, model, resolve(game=PRESET))
    st.refresh_once()
    assert st.snapshot().live == {}


def test_frame_for_bridges_registry_frames_only(tmp_path, model):
    st = StitchedSource(make_source(tmp_path), model, resolve(game=PRESET))
    assert st.frame_for("a") == FRAME and st.frame_for("b") == FRAME
    assert st.frame_for("g-1") is None                                    # ghost-only name: no frame


def test_side_asks_frames_for_the_displayed_agent(tmp_path, model):
    """Every tick the panel re-declares a frame want for the agent it shows (want_frames)."""
    dpg = pytest.importorskip("dearpygui.dearpygui")
    src = make_source(tmp_path)
    live_file(src, "a")
    calls, orig = [], model.want_frames
    model.want_frames = lambda frames, ttl: calls.append(dict(frames)) or orig(frames, ttl)
    from pokeagent.viewer.ui.window import ViewerWindow
    win = ViewerWindow(model, {}, stitched=StitchedSource(src, model, resolve(game=PRESET)))
    dpg.create_context()
    try:
        dpg.add_window(tag=win._win)
        win.stitched.build(headless=True)
        win.set_view_mode("world")
        win.stitched.tick()
        assert calls and "a" in calls[-1]
    finally:
        dpg.destroy_context()
