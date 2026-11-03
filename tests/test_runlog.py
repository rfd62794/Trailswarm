import json
from datetime import datetime

from pokeagent.agent import RunResult
from pokeagent.runlog import RunLog


def _entry(step, **kw):
    return {
        "step": step,
        "state": {"map_id": 0x26},
        "button": "A",
        "thinking": "t",
        "note": "",
        "error": "",
        "backend_ms": 5,
        **kw,
    }


def test_creates_timestamped_run_dir(tmp_path):
    log = RunLog(tmp_path / "runs", now=datetime(2026, 11, 2, 22, 30, 0))
    assert log.run_dir == tmp_path / "runs" / "20261102-223000"
    assert log.run_dir.is_dir()


def test_second_run_same_second_gets_suffixed_dir(tmp_path):
    now = datetime(2026, 11, 2, 22, 30, 0)
    first = RunLog(tmp_path / "runs", now=now)
    second = RunLog(tmp_path / "runs", now=now)
    assert second.run_dir != first.run_dir
    assert second.run_dir.name == "20261102-223000-1"


def test_append_writes_one_jsonl_line(tmp_path):
    log = RunLog(tmp_path / "runs")
    log.append(_entry(1))
    log.append(_entry(2, button="DOWN"))
    lines = log.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["step"] == 1
    assert json.loads(lines[1])["button"] == "DOWN"


def test_recent_caps_at_n(tmp_path):
    log = RunLog(tmp_path / "runs")
    for i in range(1, 16):
        log.append(_entry(i))
    recent = log.recent(10)
    assert len(recent) == 10
    assert recent[0]["step"] == 6
    assert recent[-1]["step"] == 15


def test_notes_empty_when_file_absent(tmp_path):
    log = RunLog(tmp_path / "runs")
    assert log.notes() == ""


def test_add_note_appends_lines(tmp_path):
    log = RunLog(tmp_path / "runs")
    log.add_note("first")
    log.add_note("second")
    assert log.notes() == "first\nsecond\n"


def test_notes_trim_keeps_newest_4000_at_line_boundary(tmp_path):
    log = RunLog(tmp_path / "runs")
    log.add_note("x" * 3990)  # 3991 chars with newline
    log.add_note("y" * 100)  # pushes the file past 4000
    body = log.notes()
    assert len(body) <= 4000
    # cut at a line boundary: the partial first line is dropped entirely
    assert body == "y" * 100 + "\n"


def test_state_path_format(tmp_path):
    log = RunLog(tmp_path / "runs")
    assert log.state_path(7) == log.run_dir / "state_0007.state"
    assert log.state_path(120) == log.run_dir / "state_0120.state"


def test_write_summary(tmp_path):
    log = RunLog(tmp_path / "runs")
    log.write_summary(
        RunResult(steps=3, stop_reason="max_steps", run_dir=log.run_dir, failures=1)
    )
    data = json.loads((log.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert data["steps"] == 3
    assert data["stop_reason"] == "max_steps"
    assert data["failures"] == 1
    assert data["run_dir"] == str(log.run_dir)
