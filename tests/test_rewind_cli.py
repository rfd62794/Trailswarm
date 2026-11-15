"""``pokeagent rewind``: exit code 2 on an unknown run, --json shape, text summary, registration."""
import json

from pokeagent import cli

RUN = "explore-20261115-120000-1"


def _runs(tmp_path):
    """A tiny synthetic run folder under tmp_path/runs (never a real run directory)."""
    run = tmp_path / "runs" / RUN
    run.mkdir(parents=True)
    transitions = [
        {"step": 0, "from": [1, 0, 0], "to": [1, 0, 1], "button": "UP", "moved": True,
         "textbox": "none", "text": "", "facing": "UP", "source": "agent",
         "battle_flag": 0, "battle_turn": 0},
        {"step": 1, "from": [1, 0, 1], "to": [1, 0, 2], "button": "UP", "moved": True,
         "textbox": "none", "text": "", "facing": "UP", "source": "agent",
         "battle_flag": 0, "battle_turn": 0},
        {"step": 2, "from": [1, 0, 2], "to": [2, 0, 0], "button": "UP", "moved": True,
         "textbox": "none", "text": "", "facing": "UP", "source": "agent",
         "battle_flag": 0, "battle_turn": 0},
    ]
    decisions = [
        {"step": 0, "behaviour": "frontier", "rule": "walk", "button": "UP", "map": 1, "x": 0,
         "y": 0, "goal_stage": "first_pokemon", "box": False, "battle": False,
         "outcome": "moved", "reversal": False},
    ]
    for name, rows in (("transitions.jsonl", transitions), ("decisions.jsonl", decisions)):
        (run / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path / "runs"


def test_unknown_run_exits_2_with_one_stderr_line(tmp_path, capsys):
    assert cli.main(["rewind", "no-such-run", "--runs", str(_runs(tmp_path))]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert len(out.err.strip().splitlines()) == 1 and "no-such-run" in out.err


def test_default_summary_is_three_lines(tmp_path, capsys):
    assert cli.main(["rewind", RUN, "--runs", str(_runs(tmp_path))]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    assert "steps 0-2 (3 steps)" in lines[0]
    assert lines[1].startswith("activity:") and "move" in lines[1]
    assert lines[2].startswith("moments:") and "map_change" in lines[2]


def test_json_parses_and_has_the_summary_keys(tmp_path, capsys):
    assert cli.main(["rewind", RUN, "--runs", str(_runs(tmp_path)), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["run"] == RUN and s["steps"] == {"first": 0, "last": 2, "count": 3}
    assert s["activity"]["move"] == 1.0 and s["moment_counts"]["map_change"] == 1


def test_at_segments_moments_json(tmp_path, capsys):
    runs = str(_runs(tmp_path))
    argv = ["rewind", RUN, "--runs", runs, "--at", "1", "--segments", "--moments", "--json"]
    assert cli.main(argv) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["frame"]["step"] == 1 and s["frame"]["y"] == 2 and s["frame"]["behaviour"] == "frontier"
    assert s["segments"] == [{"activity": "move", "end": 2, "start": 0}]
    assert any(m["kind"] == "map_change" for m in s["moments"])


def test_at_prints_the_frame_as_text(tmp_path, capsys):
    assert cli.main(["rewind", RUN, "--runs", str(_runs(tmp_path)), "--at", "99"]) == 0
    out = capsys.readouterr().out
    assert "frame 2:" in out and "map 2 (0,0)" in out      # clamped to the last step
