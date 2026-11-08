"""procedures_mine: a fixture runs/ tree proves the segment rule, compression, grading-respect and clean exit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import procedures_mine  # noqa: E402


def _row(step, frm, to, button="UP", moved=True, textbox="none", facing="UP"):
    return {"step": step, "from": frm, "to": to, "button": button, "moved": moved,
            "textbox": textbox, "facing": facing, "source": "agent"}


def _fixture(tmp_path):
    runs = tmp_path / "runs"
    r1 = runs / "explore-20260101-000000-1"
    r2 = runs / "explore-20260101-000100-2"
    r1.mkdir(parents=True)
    r2.mkdir(parents=True)
    rows1 = [_row(i, [3, 4, i], [3, 4, i + 1]) for i in range(1, 5)]            # steps 1-4 (to_route1 at 4)
    rows1 += [_row(i, [12, 4, i - 1], [12, 4, i]) for i in range(5, 17)]        # steps 5-16: 12 straight moves
    rows1 += [_row(17, [12, 4, 16], [12, 4, 16], button="A", moved=False),      # a press that opens a dialog
             _row(18, [12, 4, 16], [12, 4, 16], button="A", moved=False, textbox="dialog"),
             _row(19, [12, 4, 16], [1, 4, 8])]                                  # a warp: to_viridian at step 19
    (r1 / "transitions.jsonl").write_text("\n".join(json.dumps(r) for r in rows1), encoding="utf-8")
    rows2 = [_row(i, [3, 4, i], [3, 4, i + 1]) for i in range(1, 31)]           # a slower run: 22-press segment
    (r2 / "transitions.jsonl").write_text("\n".join(json.dumps(r) for r in rows2), encoding="utf-8")
    ms = {"to_route1": [{"run": r1.name, "step": 4}, {"run": r2.name, "step": 8}],
          "to_viridian": [{"run": r1.name, "step": 19}, {"run": r2.name, "step": 30}],
          "to_pewter": [{"run": r1.name, "step": 19}]}
    (runs / "milestones.json").write_text(json.dumps(ms), encoding="utf-8")
    battles = [{"start": 7, "end": 11, "kind": 2, "won": True, "run": r1.name, "battle_map": 12, "end_map": 12,
                "trainer": {"map": 12, "pic": 1, "x": 4, "y": 8}},
               {"start": 9, "end": 10, "kind": 1, "won": True, "run": r1.name}]  # a wild fight: noise
    (runs / "battles.jsonl").write_text("\n".join(json.dumps(b) for b in battles), encoding="utf-8")
    return runs


def test_mines_the_shortest_segment_into_steps(tmp_path):
    runs = _fixture(tmp_path)
    out = tmp_path / "procedures"
    assert procedures_mine.main(["--runs", str(runs), "--out", str(out), "--goal", "to_viridian"]) == 0
    proc = json.loads((out / "to_viridian.json").read_text(encoding="utf-8"))
    assert proc["source"] == "mined" and proc["goal"] == "to_viridian"
    kinds = [s["action"]["kind"] for s in proc["steps"]]
    assert kinds == ["behaviour", "goto", "interact", "goto"]
    assert proc["steps"][0]["action"]["at"] == [12, 4, 8]         # the trainer fight (kind 2), wild fight dropped
    assert proc["steps"][1]["action"] == {"kind": "goto", "map": 12, "x": 4, "y": 16}   # 12-move waypoint
    assert proc["steps"][2]["action"] == {"kind": "interact", "map": 12, "x": 4, "y": 16, "face": "UP"}
    assert proc["steps"][3]["action"] == {"kind": "goto", "map": 1, "x": 4, "y": 8}     # the warp
    assert all(s["ok"] == 0 and s["fail"] == 0 for s in proc["steps"])


def test_skips_under_length_segments(tmp_path):
    runs = _fixture(tmp_path)
    out = tmp_path / "procedures"
    procedures_mine.main(["--runs", str(runs), "--out", str(out), "--goal", "to_pewter"])
    assert not (out / "to_pewter.json").exists()


def test_never_overwrites_a_better_graded_procedure_without_force(tmp_path):
    runs = _fixture(tmp_path)
    out = tmp_path / "procedures"
    out.mkdir()
    graded = {"version": 1, "goal": "to_viridian", "source": "mined", "attempts": 5, "successes": 4,
              "best_frames": None, "best_presses": None, "disabled": False, "fail_streak": 0, "steps": []}
    (out / "to_viridian.json").write_text(json.dumps(graded), encoding="utf-8")
    procedures_mine.main(["--runs", str(runs), "--out", str(out), "--goal", "to_viridian"])
    assert json.loads((out / "to_viridian.json").read_text())["attempts"] == 5
    procedures_mine.main(["--runs", str(runs), "--out", str(out), "--goal", "to_viridian", "--force"])
    assert json.loads((out / "to_viridian.json").read_text())["attempts"] == 0


def test_missing_runs_dir_is_a_clean_zero(tmp_path):
    assert procedures_mine.main(["--runs", str(tmp_path / "nope")]) == 0
