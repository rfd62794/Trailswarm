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


def test_viewer_main_parses_the_four_new_args(monkeypatch):
    seen = []
    monkeypatch.setattr(viewer_app, "run", lambda root, **kw: seen.append(kw) or 0)
    assert viewer_app.main(["--source", "runs/x", "--game", "g", "--preset", "p", "--genre", "e"]) == 0
    assert (seen[-1]["source"], seen[-1]["game"], seen[-1]["preset"], seen[-1]["genre"]) == \
        ("runs/x", "g", "p", "e")
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
