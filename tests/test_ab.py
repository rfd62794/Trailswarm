"""tools/ab.py and pokeagent.evaluation_ab on synthetic run dirs (no emulator)."""
from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

from pokeagent.evaluation_ab import extract_metrics, sign_test_p, summarize

AB = Path(__file__).resolve().parents[1] / "tools" / "ab.py"
spec = importlib.util.spec_from_file_location("ab_tool", AB)
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


def dec(step, x=0, battle=False, rule="goto", **kw):
    return {"step": step, "rule": rule, "map": 1, "x": x, "y": 0, "battle": battle, **kw}


def make_run(tmp_path, decisions, goals):
    (tmp_path / "decisions.jsonl").write_text("\n".join(json.dumps(d) for d in decisions) + "\n")
    (tmp_path / "goal_frames.jsonl").write_text("".join(json.dumps(g) + "\n" for g in goals))
    return tmp_path


def test_extract_metrics(tmp_path):
    ds = [dec(1, 0), dec(2, 1, battle=True), dec(3, 2, battle=True), dec(4, 3), dec(5, 4, battle=True),
          dec(6, 4, rule="stall_escalate"), {"event": "blackout", "step": 6}, {"event": "item_tossed", "step": 7}]
    m = extract_metrics(make_run(tmp_path, ds, [{"goal": "other", "step": 2, "frame": 9}, {"goal": "g", "step": 50, "frame": 800}]), "g", 100)
    assert (m["solved"], m["steps"], m["frames"]) == (True, 50, 800)
    assert (m["presses"], m["battles"], m["stalls"], m["blackouts"], m["item_tossed"]) == (6, 2, 1, 1, 1)


def test_extract_unsolved_and_no_progress_window(tmp_path):
    ds = [dec(i, 0) for i in range(601)]  # one new tile, then 600 revisits = one no-progress window
    m = extract_metrics(make_run(tmp_path, ds, []), "g")
    assert m["solved"] is False and m["steps"] is None and m["stalls"] == 1


def test_extract_missing_files(tmp_path):
    assert extract_metrics(tmp_path, "g")["presses"] == 0


def test_sign_test_and_summary():
    assert sign_test_p([1, 2, 3, 4, 5]) == 0.0625
    assert sign_test_p([0, 0]) == 1.0
    mk = lambda s: {"solved": s is not None, "steps": s}  # noqa: E731
    few = summarize([mk(10), mk(None)], [mk(5), mk(8)], 100)
    assert few["test"] == "too few seeds" and few["p_value"] is None
    assert few["paired_diffs"] == [-5, -92] and few["a"]["solve_rate"] == 0.5 and few["a"]["median_steps"] == 10
    five = summarize([mk(10)] * 5, [mk(5)] * 5, 100)
    assert five["test"] == "sign test" and five["p_value"] == 0.0625


def args_for(**kw):
    return Namespace(rom="r.gb", state="s.state", steps=3000, goal="to_bill", **kw)


def test_build_cmd_flags_and_refs():
    root = Path("/x")
    plain = ab.build_cmd(root, args_for(), "", 2, None)
    assert "--maps-copy" not in plain and plain[plain.index("--seed") + 1] == "2" and "--stop-at-goal" in plain
    flagged = ab.build_cmd(root, args_for(), "--bandit --par-follow", 1, "m.json")
    assert flagged[-2:] == ["--bandit", "--par-follow"] and flagged[flagged.index("--maps-copy") + 1] == "m.json"
    assert str(root / "tools" / "explore_headless.py") in ab.build_cmd(root, args_for(), "", 1, None)


def test_dry_run_prints_commands(capsys):
    rc = ab.main(["--state", "s.state", "--goal", "to_bill", "--seeds", "1-2", "--b", "--bandit", "--b-ref", "abc123",
                  "--maps", "nope.json", "--dry-run"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0 and len(out) == 4
    assert out[0].startswith("[A seed 1]") and "--bandit" not in out[0]
    assert out[1].startswith("[B seed 1]") and "--bandit" in out[1] and "<worktree@abc123>" in out[1]


def test_list(tmp_path, capsys):
    rec = {"ts": "t", "label": "L", "state": "s/x.state", "goal": "g", "seeds": [1], "a_flags": "", "b_flags": "--bandit",
           "a_ref": None, "b_ref": None, "summary": summarize([{"solved": True, "steps": 5}], [{"solved": False, "steps": None}], 9)}
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(rec) + "\n")
    ab.main(["list", "--results", str(p)])
    assert "L" in capsys.readouterr().out
