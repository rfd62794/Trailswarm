"""tools/map_view.py is a thin launcher onto ``pokeagent view --mode world --source ...``;
the four new arguments reach ``viewer.app.run`` through ``main`` and through ``pokeagent view``."""
import importlib.util
from pathlib import Path

import pytest

from pokeagent.viewer import app as viewer_app


def _load_map_view():
    path = Path(__file__).resolve().parents[1] / "tools" / "map_view.py"
    spec = importlib.util.spec_from_file_location("map_view_launcher", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_args_for_builds_the_viewer_argv():
    mv = _load_map_view()
    assert mv.args_for("runs/x", "g") == ["--mode", "world", "--source", "runs/x", "--game", "g"]
    assert mv.args_for("runs/x") == ["--mode", "world", "--source", "runs/x"]
    assert mv.args_for("runs/x", preset="p", genre="e") == [
        "--mode", "world", "--source", "runs/x", "--preset", "p", "--genre", "e"]


def test_launcher_hands_argv_to_viewer_main(monkeypatch):
    mv = _load_map_view()
    seen = []
    monkeypatch.setattr(viewer_app, "main", lambda argv: seen.append(list(argv)) or 0)
    assert mv.main(["runs/x", "--game", "g"]) == 0
    assert seen == [["--mode", "world", "--source", "runs/x", "--game", "g"]]


def test_viewer_main_parses_the_four_new_args(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(viewer_app, "run", lambda root, **kw: seen.append(kw) or 0)
    src = str(tmp_path)
    assert viewer_app.main(["--source", src, "--game", "super-mario-land", "--preset", "flip-screen",
                            "--genre", "platformer"]) == 0
    assert (seen[-1]["source"], seen[-1]["game"], seen[-1]["preset"], seen[-1]["genre"]) == (
        src, "super-mario-land", "flip-screen", "platformer")
    assert viewer_app.main([]) == 0 and seen[-1]["source"] is None    # unchanged without --source


def test_stitched_source_none_without_source_or_for_rom_world(tmp_path):
    """No --source: no stitched source (rom-world renderer, unchanged); a rom-world preset with a
    source also yields no stitched source."""
    from pokeagent.viewer.model import ViewerModel
    assert viewer_app._stitched_source(None, ViewerModel(), None, None, None) is None
    st = viewer_app._stitched_source(tmp_path, ViewerModel(), None, "rpg-overworld", None)
    assert st is None                                    # a rom-world preset keeps the Kanto renderer
    st = viewer_app._stitched_source(tmp_path, ViewerModel(), None, "flip-screen", None)
    assert st is not None
    st.close()


def test_pokeagent_view_accepts_the_four_args(monkeypatch):
    seen = []
    monkeypatch.setattr(viewer_app, "run", lambda root, **kw: seen.append(kw) or 0)
    from pokeagent.cli import _build_parser
    a = _build_parser().parse_args(["view", "--source", "runs/x", "--game", "g",
                                    "--preset", "p", "--genre", "e"])
    assert a.func(a) == 0
    assert (seen[-1]["source"], seen[-1]["game"], seen[-1]["preset"], seen[-1]["genre"]) == \
        ("runs/x", "g", "p", "e")


# --- review fixes: fps/refresh, rom-world warning, name validation, --source checks, idempotent start ---

def test_launcher_forwards_fps_and_refresh(monkeypatch):
    mv = _load_map_view()
    assert mv.args_for("runs/x", fps=60, refresh=2.5) == [
        "--mode", "world", "--source", "runs/x", "--fps", "60", "--refresh", "2.5"]
    seen = []
    monkeypatch.setattr(viewer_app, "main", lambda argv: seen.append(list(argv)) or 0)
    assert mv.main(["runs/x", "--fps", "60", "--refresh", "2.0"]) == 0
    assert seen == [["--mode", "world", "--source", "runs/x", "--fps", "60", "--refresh", "2.0"]]


def test_viewer_main_passes_fps_and_refresh(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(viewer_app, "run", lambda root, **kw: seen.append((kw, root)) or 0)
    assert viewer_app.main(["--source", str(tmp_path), "--fps", "60", "--refresh", "0.5"]) == 0
    assert seen[-1][0]["refresh"] == 0.5 and seen[-1][0]["fps"] == 60


def test_stitched_source_gets_refresh_and_fps(tmp_path):
    from pokeagent.viewer.model import ViewerModel
    st = viewer_app._stitched_source(tmp_path, ViewerModel(), None, "flip-screen", None, fps=45, refresh=0.75)
    assert (st.fps, st.refresh) == (45, 0.75)
    st.close()


def test_source_with_rom_world_renderer_warns_on_stderr(tmp_path, capsys):
    from pokeagent.viewer.model import ViewerModel
    assert viewer_app._stitched_source(tmp_path, ViewerModel(), "pokemon-red", None, None) is None
    err = capsys.readouterr().err
    assert "--source" in err and "rom-world" in err


@pytest.mark.parametrize("flag", ["--game", "--preset", "--genre"])
def test_unknown_name_exits_listing_valid_names(monkeypatch, tmp_path, capsys, flag):
    monkeypatch.setattr(viewer_app, "run", lambda *a, **k: pytest.fail("must not open a window"))
    with pytest.raises(SystemExit) as e:
        viewer_app.main([flag, "typo-name"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "typo-name" in err and "valid:" in err
    assert ("super-mario-land" if flag != "--genre" else "platformer") in err


def test_known_names_still_accepted(monkeypatch):
    seen = []
    monkeypatch.setattr(viewer_app, "run", lambda root, **kw: seen.append(kw) or 0)
    assert viewer_app.main(["--game", "super-mario-land", "--preset", "flip-screen", "--genre", "platformer"]) == 0


def test_missing_source_dir_exits_with_message(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(viewer_app, "run", lambda *a, **k: pytest.fail("must not open a window"))
    with pytest.raises(SystemExit) as e:
        viewer_app.main(["--source", str(tmp_path / "nope")])
    assert e.value.code == 2 and "not an existing directory" in capsys.readouterr().err


def test_unreadable_store_gives_empty_map(monkeypatch, tmp_path):
    from pokeagent.mapview.presets import resolve
    from pokeagent.viewer import stitched_source as ss
    from pokeagent.viewer.model import ViewerModel

    def boom(*a, **k):
        raise OSError("unreadable")
    monkeypatch.setattr(ss, "snapshot_once", boom)
    st = ss.StitchedSource(tmp_path, ViewerModel(), resolve(preset="flip-screen"))
    snap = st.snapshot()
    assert snap.areas == () and snap.live == {}


def test_start_is_idempotent(monkeypatch, tmp_path):
    from pokeagent.mapview.presets import resolve
    from pokeagent.viewer import stitched_source as ss
    from pokeagent.viewer.model import ViewerModel
    started = []
    monkeypatch.setattr(ss.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: started.append(1)})())
    st = ss.StitchedSource(tmp_path, ViewerModel(), resolve(preset="flip-screen"))
    st.start()
    st.start()
    assert len(started) == 2        # two daemons once, not four
