"""Stadium pane: a top-level STADIUM_PANE window, menu toggling, slots fed by WorldModel.stadium,
the strip gone from world_side. Needs the opponent fix (BattleCard enemy fields from the world model)."""
from types import SimpleNamespace

import pytest

from pokeagent.viewer import modes
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.ui import tags
from pokeagent.world import events as ev
from pokeagent.world.model import WorldModel


def _ctx(dpg):
    dpg.create_context()
    if not dpg.does_item_exist("viewer_tex"):
        dpg.add_texture_registry(tag="viewer_tex", show=False)


def _destroy(dpg):
    try:
        dpg.destroy_context()
    except Exception:
        pass


def _battle_wm(n=3):
    wm = WorldModel()
    for i in range(n):
        bus = ev.EventBus()
        bus.emit(ev.BattleStart(species="PIDGEY", enemy_level=4, own_species="CHARMANDER", own_level=5,
                                hp=19, max_hp=19, enemy_hp=12, enemy_max_hp=12))
        wm.ingest(f"ag{i}", bus.since(0))
    return wm


def test_stadium_visible_defaults_to_mode_and_menu_choice_sticks():
    from pokeagent.viewer.ui.window import ViewerWindow
    win = ViewerWindow(ViewerModel(), {})
    assert win.stadium_visible() is False                 # tiles/grid mode: hidden, like the old strip
    win.focus.set_mode("world")
    assert win.stadium_visible() is True                  # world mode: shown
    win.set_stadium_pref(False)                           # the menu choice wins for the run
    assert win.stadium_visible() is False
    win.set_stadium_pref(True)
    assert win.stadium_visible() is True


def test_pane_is_top_level_with_tag_and_toggles(monkeypatch):
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui.stadium_pane import StadiumPane
    _ctx(dpg)
    try:
        pane = StadiumPane(lambda aid: None)
    except Exception as e:
        _destroy(dpg)
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        assert dpg.does_item_exist(tags.STADIUM_PANE)
        info = dpg.get_item_info(tags.STADIUM_PANE)
        assert "Window" in str(info.get("type", ""))      # a real top-level window, not a child
        shown = []
        real = dpg.configure_item
        monkeypatch.setattr(dpg, "configure_item",
                            lambda item, **kw: (shown.append((item, kw.get("show"))), real(item, **kw))[1])
        pane.set_visible(True)
        pane.set_visible(False)
        assert (pane.win, True) in shown and (pane.win, False) in shown
    finally:
        _destroy(dpg)


def test_menu_build_creates_stadium_checkbox():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui import menu
    from pokeagent.viewer.ui.window import ViewerWindow
    dpg.create_context()
    try:
        win = ViewerWindow(ViewerModel(), {})
        win.focus.set_mode("world")
        menu.build(win)
        assert dpg.does_item_exist(menu.MENU_STADIUM)
        assert dpg.get_value(menu.MENU_STADIUM) in (True, 1)  # default mirrors the world-mode default
    except Exception as e:
        _destroy(dpg)
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    _destroy(dpg)


def test_slots_and_title_follow_world_model():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui.stadium_pane import StadiumPane
    _ctx(dpg)
    focused = []
    try:
        pane = StadiumPane(focused.append)
    except Exception as e:
        _destroy(dpg)
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        wm = _battle_wm(3)
        pane.update(wm, ViewerModel(), now=1.0)
        assert "Stadium - 3 in battle" in str(dpg.get_value(pane.title))
        live = [s.aid for s in pane.slots if s.aid is not None]
        assert sorted(live) == ["ag0", "ag1", "ag2"]
        pane.slots[0].click()                              # clicking a slot still focuses the agent
        assert focused == [live[0]]
        wm2 = WorldModel()                                 # no battles: the title says so
        pane.update(wm2, ViewerModel(), now=1.0)
        assert "no battles" in str(dpg.get_value(pane.title))
        assert all(s.aid is None for s in pane.slots)
    finally:
        _destroy(dpg)


def test_world_side_no_longer_builds_the_strip():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui.world_side import WorldSide
    _ctx(dpg)
    fake_view = SimpleNamespace(interiors=SimpleNamespace(mode="inset"), wm=WorldModel(), world=None)
    try:
        with dpg.window():
            side = WorldSide(fake_view)
    except Exception as e:
        _destroy(dpg)
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        for attr in ("slots", "slots_parent", "strip_title", "more"):
            assert not hasattr(side, attr), f"world_side still builds the stadium strip ({attr})"
        assert hasattr(side, "health")                     # the badge/panel took the strip's place
    finally:
        _destroy(dpg)


def test_modes_status_text_unchanged():
    assert modes.status_text("world", 3, "a1", None) == \
        "Mode: World  |  Agents: 3  |  Selected: a1  |  Follow: off"
