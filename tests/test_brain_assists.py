"""brain assists: clusters, per-goal unaided flags and milestone_unaided over a synthetic run."""
import io
import json
from contextlib import redirect_stdout

import pokeagent.brain as brain
from pokeagent.cli_brain import main as brain_main

LADDER = ["g0", "g1", "g2", "g3", "g4"]
INITIAL = ["g0"]
SECRET = "SECRET_DIALOG_NEVER_EMITTED"


def _press(step, frm, button, to, source, text=""):
    return {"step": step, "from": frm, "button": button, "to": to, "moved": frm != to,
            "textbox": "dialog" if text else "none", "text": text, "facing": "UP",
            "source": source}


def _transitions():
    return [
        _press(1, [1, 0, 0], "UP", [1, 0, 1], "agent"),
        _press(2, [1, 0, 1], "UP", [1, 0, 2], "human", text=SECRET),
        _press(3, [1, 0, 2], "A", [1, 0, 2], "human", text=SECRET),
        _press(4, [1, 0, 2], "UP", [1, 0, 3], "agent"),
        _press(10, [1, 0, 3], "B", [1, 0, 3], "claude"),
        _press(12, [2, 1, 1], "LEFT", [2, 0, 1], "human"),   # map change -> new cluster
        _press(40, [2, 0, 1], "LEFT", [2, 0, 0], "human"),   # step gap > 20 -> new cluster
        _press(41, [2, 0, 0], "UP", [2, 0, 1], "agent"),
    ]


def _goal_frames():
    return [{"goal": "g1", "step": 5, "frame": 100},
            {"goal": "g2", "step": 15, "frame": 300},
            {"goal": "g3", "step": 30, "frame": 500}]


def test_clusters_by_map_change_and_step_gap():
    out = brain.assists_report(_transitions(), _goal_frames(), INITIAL, LADDER, gap=20)
    assert out["total_presses"] == 8 and out["assist_presses"] == 5
    assert out["by_source"] == {"agent": 3, "human": 4, "claude": 1}
    assert len(out["clusters"]) == 3
    c0, c1, c2 = out["clusters"]
    # steps 2,3 (human) and 10 (claude): same map, gaps <= 20 -> one cluster
    assert (c0["map"], c0["step_start"], c0["step_end"], c0["presses"]) == (1, 2, 10, 3)
    assert c0["by_source"] == {"human": 2, "claude": 1}
    assert c0["buttons"] == {"UP": 1, "A": 1, "B": 1}
    assert c0["goal_stage"] == "g1"          # g0 is initial; g1 reached at step 5 > 2
    assert (c1["map"], c1["step_start"], c1["presses"]) == (2, 12, 1)
    assert c1["by_source"] == {"human": 1} and c1["buttons"] == {"LEFT": 1}
    assert c1["goal_stage"] == "g2"          # g1 reached at 5; g2 not until 15
    assert (c2["map"], c2["step_start"], c2["presses"]) == (2, 40, 1)
    assert c2["goal_stage"] == "g4"          # g1..g3 all reached by step 40
    assert out["final_stage"] == "g4"


def test_goal_ends_and_unaided():
    out = brain.assists_report(_transitions(), _goal_frames(), INITIAL, LADDER)
    ends = out["goal_ends"]
    assert [(e["goal"], e["step"], e["assists_in_stage"], e["unaided"]) for e in ends] == [
        ("g1", 5, 2, False),   # human presses at steps 2,3 inside stage
        ("g2", 15, 2, False),  # claude at 10 and human at 12
        ("g3", 30, 0, True),   # next assist press is step 40, after the goal's stage
    ]
    assert out["unaided_goals"] == ["g3"]
    assert out["milestone_unaided"] is False


def test_milestone_unaided_true():
    trans = [_press(1, [1, 0, 0], "UP", [1, 0, 1], "agent"),
             _press(4, [1, 0, 1], "UP", [1, 0, 2], "agent")]
    out = brain.assists_report(trans, [{"goal": "g1", "step": 3, "frame": 1}], [], LADDER)
    assert out["assist_presses"] == 0 and out["clusters"] == []
    assert out["goal_ends"] == [{"goal": "g1", "step": 3, "assists_in_stage": 0, "unaided": True}]
    assert out["unaided_goals"] == ["g1"] and out["milestone_unaided"] is True


def test_missing_goal_frames_tolerated():
    out = brain.assists_report(_transitions(), [], INITIAL, LADDER)
    assert out["goal_ends"] == [] and out["unaided_goals"] == []
    assert out["milestone_unaided"] is False
    assert out["clusters"][0]["goal_stage"] == "g1"  # no reached goals: first non-initial stage


def test_no_dialogue_leaks_into_output():
    out = brain.assists_report(_transitions(), _goal_frames(), INITIAL, LADDER)
    assert SECRET not in json.dumps(out)


def test_gap_zero_splits_every_assist():
    out = brain.assists_report(_transitions(), _goal_frames(), INITIAL, LADDER, gap=0)
    assert len(out["clusters"]) == 5  # every assist press its own cluster


# --- CLI ---

def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = brain_main(argv)
    return rc, buf.getvalue()


def test_cli_assists(tmp_path):
    run = tmp_path / "run1"
    run.mkdir()
    lines = [json.dumps(t) for t in _transitions()[:4]]
    (run / "transitions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({"initial_goals": ["potion"]}), encoding="utf-8")
    rc, out = _run(["assists", str(run)])
    assert rc == 0
    rep = json.loads(out)
    assert rep["total_presses"] == 4 and rep["assist_presses"] == 2
    assert rep["clusters"][0]["presses"] == 2 and rep["goal_ends"] == []
    rc, out = _run(["assists", str(tmp_path / "no-such-run")])
    assert rc == 1
