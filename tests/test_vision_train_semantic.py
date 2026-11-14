"""vision_train --labels semantic: the shared-class run, its output dir, and its refusals."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from pokeagent.vision.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "vision_train_tool", ROOT / "tools" / "vision_train.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_dataset(root, semantic=True):
    """Three areas, one walkable tile row and one npc sprite row each (distinct images)."""
    store = Store(root)
    for i, area in enumerate(("map-1", "map-2", "map-3")):
        store.add_crop("tile", 5, "terrain", area, "r0c0", 0, 0, 8, 8, 2,
                       np.full((8, 8, 3), 10 + i, np.uint8))
        store.add_crop("sprite", 13, "npc", area, "r1c1", 0, 0, 16, 16, None,
                       np.full((16, 16, 3), 200 + i, np.uint8))
    store.flush()
    if semantic:
        path = root / "samples.jsonl"
        rows = [json.loads(ln) for ln in path.read_text().splitlines()]
        for r in rows:
            r["semantic"] = "walkable" if r["kind"] == "tile" else "npc"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root


def test_semantic_flag_runs_and_writes_only_under_game_semantic(tmp_path, monkeypatch, capsys):
    mod = _load_tool()
    monkeypatch.chdir(tmp_path)
    root = _write_dataset(tmp_path / "ds")
    rc = mod.main(["--game", "g", "--root", str(root), "--labels", "semantic",
                   "--epochs", "1", "--max-seconds", "30"])
    out = capsys.readouterr().out
    assert "template: overall" in out and "walkable" in out
    models = tmp_path / "runs" / "vision_models"
    try:
        import torch  # noqa: F401
    except ImportError:
        assert rc == 2 and not models.exists()
    else:
        assert rc == 0 and "net: overall" in out
        assert "class      support   template  net" in out
        rep = json.loads((models / "g-semantic" / "report.json").read_text())
        assert rep["labels"] == "semantic"
        assert not (models / "g").exists()


def test_semantic_without_labels_exits_2(tmp_path, monkeypatch, capsys):
    mod = _load_tool()
    monkeypatch.chdir(tmp_path)
    root = _write_dataset(tmp_path / "ds", semantic=False)
    rc = mod.main(["--game", "g", "--root", str(root), "--labels", "semantic"])
    assert rc == 2
    assert "no semantic labels" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_specific_never_calls_as_semantic(tmp_path, monkeypatch):
    mod = _load_tool()
    monkeypatch.chdir(tmp_path)
    root = _write_dataset(tmp_path / "ds")
    calls = []
    monkeypatch.setattr(mod.semantic_view, "as_semantic",
                        lambda ds: calls.append(ds) or ds)
    mod.main(["--game", "g", "--root", str(root), "--epochs", "1", "--max-seconds", "30"])
    assert calls == []


def test_semantic_net_report(tmp_path, monkeypatch, capsys):
    pytest.importorskip("torch")
    mod = _load_tool()
    monkeypatch.chdir(tmp_path)
    root = _write_dataset(tmp_path / "ds")
    rc = mod.main(["--game", "g", "--root", str(root), "--labels", "semantic",
                   "--epochs", "2", "--threads", "1", "--max-seconds", "60"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "net: overall" in out and "template=" in out
    out_dir = tmp_path / "runs" / "vision_models" / "g-semantic"
    assert (out_dir / "weights.pt").is_file() and (out_dir / "report.json").is_file()
