"""The offline cell census on synthetic run dirs: usable-row filtering, block sweep, monotone
goals count, out-of-order goals, missing files, and the tools/cell_census.py wrapper."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pokeagent.explorer.decisions import make_record
from pokeagent.goexplore import census as cz

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _tool(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}_gc", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def press(step, map_id, x, y, stage):
    return make_record(step, "explore", "walk", "a", (map_id, x, y), stage, False, False, "moved")


def write_run(base, name, rows, goal_frames=None):
    d = base / name
    d.mkdir()
    lines = [json.dumps(r) if isinstance(r, dict) else r for r in rows]
    (d / "decisions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if goal_frames is not None:
        (d / "goal_frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in goal_frames),
                                             encoding="utf-8")
    return d


@pytest.fixture
def runs(tmp_path):
    """Run A: 6 tiles over two blocks, stage potion -> left_house (ordered, with junk lines tolerated).
    Run B: stage regresses left_house -> potion; goal_frames logged left_house before potion."""
    a_rows = [press(1, 1, 0, 0, "potion"), press(2, 1, 1, 0, "potion"), press(3, 1, 2, 0, "potion"),
              press(4, 1, 3, 0, "left_house"), press(5, 1, 4, 0, "left_house"),
              press(6, 1, 5, 0, "left_house"),
              {**press(7, 1, 6, 0, "left_house"), "event": "item_tossed"},   # event row: skipped, not counted
              "{corrupt",                                                   # torn tail line: skipped
              press(8, 1, 6, 0, "not_a_goal"),                              # unknown stage: skipped
              {"step": 9, "map": 1, "y": 0, "goal_stage": "potion"}]        # missing x: skipped
    a = write_run(tmp_path, "run_a", a_rows,
                  [{"goal": "potion", "step": 1, "frame": 100},
                   {"goal": "left_house", "step": 4, "frame": 400},
                   {"goal": "first_pokemon", "step": 9, "frame": 900, "skipped": True},
                   {"goal": "map:0x42", "step": 9, "frame": 901}])
    b = write_run(tmp_path, "run_b",
                  [press(1, 2, 0, 0, "left_house"), press(2, 2, 1, 0, "potion"), press(3, 2, 2, 0, "potion")],
                  [{"goal": "left_house", "step": 1, "frame": 100},
                   {"goal": "potion", "step": 2, "frame": 200}])
    return a, b


def test_census_counts_and_filtering(runs):
    c = cz.census(list(runs))
    assert c["runs"] == 2 and c["rows"] == 9 and c["skipped_rows"] == 3   # corrupt + unknown stage + missing x
    assert c["cells"] == 5
    assert c["cells_per_run"] == {"run_a": 3, "run_b": 2}
    assert c["cells_by_goals"] == {"0": 2, "1": 3}
    assert c["monotone_violations"] == {"run_b": 1}
    assert c["out_of_order_goals"] == {"run_b": ["potion"]}
    assert c["not_in_logs"] == ["flag_popcount", "party_level_bucket"]


def test_block_sweep_nondecreasing(runs):
    c = cz.census(list(runs))
    assert c["block_sweep"] == {"1": 9, "2": 7, "4": 5, "8": 4}
    n = [c["block_sweep"][k] for k in ("8", "4", "2", "1")]
    assert n == sorted(n)


def test_empty_and_missing_run_dirs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    for c in (cz.census([empty]), cz.census([tmp_path / "gone"])):
        assert c["runs"] == 0 and c["rows"] == 0 and c["cells"] == 0


def test_tool_json_and_missing_dir(runs, tmp_path, capsys):
    tool = _tool("cell_census")
    assert tool.main([str(runs[0]), str(runs[1]), "--json"]) == 0
    c = json.loads(capsys.readouterr().out)
    assert c["cells"] == 5 and c["not_in_logs"] == ["flag_popcount", "party_level_bucket"]
    assert tool.main([str(tmp_path / "does_not_exist")]) == 2
    err = capsys.readouterr().err
    assert "not found" in err and "Traceback" not in err
