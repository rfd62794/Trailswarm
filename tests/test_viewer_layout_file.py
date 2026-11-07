"""Layout persistence helpers: ensure_layout/reset_layout, the committed default ini, the tag list."""
import pytest

from pokeagent.viewer import layout_file
from pokeagent.viewer.ui import tags


def test_ensure_layout_copies_when_missing(tmp_path):
    default = tmp_path / "default.ini"
    default.write_text("[Window][Stadium]\nPos=1,2\nSize=3,4\n", encoding="utf-8")
    target = tmp_path / "runs" / "viewer" / "layout.ini"
    out = layout_file.ensure_layout(default, target)
    assert out == target and target.read_text() == default.read_text()


def test_ensure_layout_never_overwrites(tmp_path):
    default = tmp_path / "default.ini"
    default.write_text("default", encoding="utf-8")
    target = tmp_path / "layout.ini"
    target.write_text("mine", encoding="utf-8")
    layout_file.ensure_layout(default, target)
    assert target.read_text() == "mine"


def test_ensure_layout_survives_unwritable_target(tmp_path):
    default = tmp_path / "default.ini"
    default.write_text("default", encoding="utf-8")
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a dir", encoding="utf-8")
    target = blocker / "layout.ini"                       # parent cannot be created: must not raise
    assert layout_file.ensure_layout(default, target) == target


def test_reset_layout_overwrites(tmp_path):
    default = tmp_path / "default.ini"
    default.write_text("default", encoding="utf-8")
    target = tmp_path / "runs" / "viewer" / "layout.ini"
    target.parent.mkdir(parents=True)
    target.write_text("custom", encoding="utf-8")
    layout_file.reset_layout(default, target)
    assert target.read_text() == "default"


def test_committed_default_layout_ini_parses():
    text = layout_file.DEFAULT.read_text(encoding="utf-8")
    assert "[Window][" in text and "Pos=" in text and "Size=" in text


def test_documented_top_level_window_tags():
    assert set(tags.TOP_LEVEL_WINDOWS) == {tags.MAIN_WINDOW, tags.STADIUM_PANE}


def test_configure_app_supports_layout_keywords(tmp_path):
    """The installed Dear PyGui 2.x accepts init_file/docking/docking_space (a TypeError fails this)."""
    dpg = pytest.importorskip("dearpygui.dearpygui")
    dpg.create_context()
    try:
        dpg.configure_app(init_file=str(tmp_path / "layout.ini"), docking=True, docking_space=False)
    finally:
        dpg.destroy_context()


def test_populate_builds_only_documented_top_level_windows(monkeypatch):
    """Every window ``_populate`` creates is in the documented tag list (a new unlabelled window fails)."""
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    seen = []
    real_add_window = dpg.add_window

    def record(**kw):
        seen.append(kw.get("tag"))
        return real_add_window(**kw)

    win = ViewerWindow(ViewerModel(), {})
    try:
        win._build()
        dpg.setup_dearpygui()
    except Exception as e:
        try:
            dpg.destroy_context()
        except Exception:
            pass
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        monkeypatch.setattr(dpg, "add_window", record)
        win._populate()
        assert set(seen) == set(tags.TOP_LEVEL_WINDOWS)
    finally:
        dpg.destroy_context()
