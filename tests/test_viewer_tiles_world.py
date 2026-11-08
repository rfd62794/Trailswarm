"""One window, Tiles | World: mode toggle + Tab, one shared selection, card Follow, CLI --mode. Headless (no viewport)."""
import pytest

from pokeagent.viewer import modes
from pokeagent.viewer.sources import FakeSource
from test_viewer_agents import FRAME, snap


@pytest.fixture
def win():
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    model = ViewerModel()
    srcs = {i: FakeSource(i, [snap(i)], [FRAME]) for i in ("a", "b")}
    model.poll(list(srcs.values())); model.drain()
    return ViewerWindow(model, srcs)


def test_status_text_pure():
    t = modes.status_text("grid", 3, "a", None)
    assert "Mode: Tiles" in t and "Agents: 3" in t and "Selected: a" in t and "Follow: off" in t
    t = modes.status_text("world", 0, None, "a")
    assert "Mode: World" in t and "Selected: none" in t and "Follow: on (a)" in t


def test_mode_names():
    assert modes.internal("tiles") == "grid" and modes.internal("world") == "world"
    assert modes.DEFAULT_MODE == "world"


def test_toggle_swaps_modes_and_leaves_focus(win):
    assert win.focus.mode == "grid"
    win.toggle_view_mode()
    assert win.focus.view == "world"
    win.toggle_view_mode()
    assert win.focus.view == "grid"
    win.toggle_focus("a")
    win.toggle_view_mode()                      # Tab from focus view: out of focus, into World
    assert win.focus.focused is None and win.focus.view == "world"
    win.set_view_mode("bogus")
    assert win.focus.view == "world"


def test_world_click_selection_shows_in_tiles(win):
    win._on_select("b")                         # what WorldView does on a click (it also starts follow)
    win.set_view_mode("grid")
    assert win.selected == "b" and win.selected_id() == "b"
    assert "Selected: b" in win.status_line()


def test_tiles_selection_then_world_follows(win):
    win._on_select("a")
    win.set_view_mode("world")
    assert win.world.pending_follow == "a"      # view not built headless: follow is queued
    assert win.following() == "a" and "Follow: on (a)" in win.status_line()


def test_card_follow_switches_to_world_and_follows(win):
    assert win.focus.view == "grid"
    win.follow_agent("b")
    assert win.focus.view == "world" and win.selected == "b" and win.following() == "b"
    assert "Mode: World" in win.status_line()


def test_tab_is_bound_once_and_toggles():
    pytest.importorskip("dearpygui.dearpygui")
    import inspect
    from pokeagent.viewer.ui import keys
    src = inspect.getsource(keys.install)
    assert src.count("mvKey_Tab") == 1 and "toggle_view_mode" in src
    assert "Tab" not in keys._DPG_KEYS


def test_dpg_headless_follow_button_selection_and_bar():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    model = ViewerModel()
    srcs = {i: FakeSource(i, [snap(i)] * 3, [FRAME] * 3) for i in ("a", "b")}
    model.poll(list(srcs.values())); model.drain()
    win = ViewerWindow(model, srcs)
    try:
        win._build()
        dpg.setup_dearpygui()
        win._populate()
    except Exception as e:
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        win.set_view_mode("grid")
        win.tick()
        card = win._grid.cards["a"]
        assert "follow" in card._img
        dpg.get_item_callback(card._img["follow"])(None, None, None)    # the card's Follow button
        assert win.focus.view == "world" and win.world.view.follow.agent_id == "a"
        win.tick()
        assert "Mode: World" in dpg.get_value("status_line") and "Follow: on (a)" in dpg.get_value("status_line")
        dpg.get_item_callback("mode_grid")(None, None, None)           # segmented control: Tiles
        win.tick()
        assert win.focus.view == "grid" and win._grid.pin == "a"        # selected card kept on the page
        win._on_select("b")
        dpg.get_item_callback("mode_world")(None, None, None)
        assert win.world.view.follow.agent_id == "b"
    finally:
        dpg.destroy_context()


def test_cli_mode_parsing(monkeypatch):
    import pokeagent.viewer.app as app
    from pokeagent.cli import _build_parser
    seen = []
    monkeypatch.setattr(app, "run", lambda root, **kw: seen.append(kw) or 0)
    p = _build_parser()
    for argv in (["view"], ["view", "--mode", "tiles"], ["world"], ["world", "--mode", "tiles"], ["view", "--mode", "world"]):
        a = p.parse_args(argv)
        assert a.func(a) == 0
    assert [k["mode"] for k in seen] == ["world", "tiles", "world", "tiles", "world"]
    with pytest.raises(SystemExit):
        p.parse_args(["view", "--mode", "grid"])
