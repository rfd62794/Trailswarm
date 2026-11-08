"""Swarm page: a top-level SWARM_PAGE window fed by swarm_rows; a row click focuses the agent.
Headless: dpg.create_context() only - no viewport, no input; nothing may open a window."""
import importlib


def _ctx(dpg):
    dpg.create_context()
    if not dpg.does_item_exist("viewer_tex"):
        dpg.add_texture_registry(tag="viewer_tex", show=False)


def _destroy(dpg):
    try:
        dpg.destroy_context()
    except Exception:
        pass


ROWS = [{"id": "agent0", "state": "live", "segment": "to_route1", "grade": "B", "next": "to_viridian",
         "steps_s": "42", "rss": "151", "health": "ok", "reason": "", "goal": "left_house"},
        {"id": "agent1", "state": "dead", "segment": "n/a", "grade": "n/a", "next": "n/a",
         "steps_s": "", "rss": "", "health": "stalled", "reason": "no new tiles", "goal": ""}]


def test_page_is_top_level_with_tag_and_row_click_focuses():
    dpg = importlib.import_module("dearpygui.dearpygui")
    from pokeagent.viewer.ui import tags
    from pokeagent.viewer.ui.swarm_page import SwarmPage
    _ctx(dpg)
    focused = []
    try:
        page = SwarmPage(focused.append)
    except BaseException:
        _destroy(dpg)
        raise
    try:
        assert dpg.does_item_exist(tags.SWARM_PAGE)
        assert "Window" in str(dpg.get_item_info(tags.SWARM_PAGE).get("type", ""))
        page.update(ROWS)
        assert "2 agents" in str(dpg.get_value(page.title))
        assert len(page.row_items) == 2
        dpg.get_item_callback(page.row_items[1])(None, None, None)    # click a row -> focus that agent
        assert focused == ["agent1"]
        page.update(ROWS)                                             # unchanged rows: no rebuild
        assert len(page.row_items) == 2
        page.set_visible(True)
        assert dpg.get_item_configuration(tags.SWARM_PAGE)["show"] is True
        page.set_visible(False)
        assert dpg.get_item_configuration(tags.SWARM_PAGE)["show"] is False
    finally:
        _destroy(dpg)


def test_page_visibility_default_and_pref(tmp_path):
    dpg = importlib.import_module("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    dpg.create_context()
    try:
        win = ViewerWindow(ViewerModel(), {}, root=tmp_path)
        assert win.swarm_visible() is False               # no runs/swarm under this root
        (tmp_path / "runs" / "swarm").mkdir(parents=True)
        win2 = ViewerWindow(ViewerModel(), {}, root=tmp_path)
        assert win2.swarm_visible() is True               # a swarm run: the page defaults to shown
        win2.set_swarm_pref(False)                         # the menu choice wins for the run
        assert win2.swarm_visible() is False
        win2.on_swarm_close()                              # the title-bar X does the same
        assert win2.swarm_visible() is False
    finally:
        _destroy(dpg)


def test_menu_build_creates_swarm_checkbox():
    dpg = importlib.import_module("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui import menu
    from pokeagent.viewer.ui.window import ViewerWindow
    dpg.create_context()
    try:
        win = ViewerWindow(ViewerModel(), {})
        menu.build(win)
        assert dpg.does_item_exist(menu.MENU_SWARM)
        assert dpg.get_value(menu.MENU_SWARM) in (False, 0)  # no runs/swarm under cwd in tests
    finally:
        _destroy(dpg)
