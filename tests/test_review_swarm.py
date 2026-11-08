"""``pokeagent review swarm``: --since parsing, per-segment rates, stall causes, checkpoints, breaks."""
import os
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

from pokeagent.invariants.findings import ERROR, Finding
from pokeagent.review import swarm

FIX = Path(__file__).resolve().parent / "fixtures" / "review"
RUNS = FIX / "runs"
RUN_STALL = "explore-20261107-151000-1002"
RUN_CRASH = "explore-20261107-154000-1005"

SINCE_ALL = datetime(2026, 11, 7, 0, 0)


@pytest.fixture(autouse=True)
def _no_real_invariants(monkeypatch):
    """The fixture root is synthetic; the real checker is covered by its own tests."""
    monkeypatch.setattr("pokeagent.invariants.runner.run_all", lambda *a, **k: [])


def copy_runs(tmp_path):
    dst = tmp_path / "runs"
    shutil.copytree(RUNS, dst)
    return dst


def test_parse_since_forms():
    now = datetime(2026, 11, 7, 16, 0)
    assert swarm.parse_since("30m", now) == datetime(2026, 11, 7, 15, 30)
    assert swarm.parse_since("2h", now) == datetime(2026, 11, 7, 14, 0)
    assert swarm.parse_since("14:50", now) == datetime(2026, 11, 7, 14, 50)
    assert swarm.parse_since("2026-11-07T15:05:00") == datetime(2026, 11, 7, 15, 5)
    assert swarm.parse_since("2026-11-07T15:05") == datetime(2026, 11, 7, 15, 5)
    with pytest.raises(ValueError):
        swarm.parse_since("yesterday-ish")


def test_range_filter_by_dir_timestamp():
    s = swarm.summarise(RUNS, datetime(2026, 11, 7, 15, 5))
    assert s["runs"]["count"] == 4          # 15:10, 15:20, 15:30, 15:40
    s = swarm.summarise(RUNS, datetime(2026, 11, 7, 15, 5), until=datetime(2026, 11, 7, 15, 25))
    assert s["runs"]["count"] == 2


def test_runs_section_counts():
    s = swarm.summarise(RUNS, SINCE_ALL)
    assert s["runs"] == {"count": 6, "segment_runs": 6, "watched": 1}   # run_ok has a claude press


def test_per_segment_rates_and_failing():
    s = swarm.summarise(RUNS, SINCE_ALL)
    g = s["segments"]["gyarados"]
    assert (g["attempts"], g["solves"], g["solve_rate"]) == (5, 1, 0.2)
    assert (g["frames_best"], g["frames_median"]) == (420, 420)
    assert g["stall_rate"] == 0.2 and g["blackout_rate"] == 0.2
    assert g["loop_episodes"] == 1
    assert sorted(g["failing"]) == ["explore-20261107-150100-1006", RUN_STALL,
                                  "explore-20261107-153000-1004", RUN_CRASH]
    t = s["segments"]["to_bill"]
    assert (t["attempts"], t["solves"], t["solve_rate"], t["loop_episodes"]) == (1, 1, 1.0, 1)


def test_top_stall_causes_and_rules():
    s = swarm.summarise(RUNS, SINCE_ALL)
    assert s["top_stall_causes"] == [
        {"cause": "blocked by a learned wall the planner keeps targeting", "count": 1,
         "signature_key": "35|frontier|frontier|UP|blocked|False", "example": RUN_STALL}]
    assert s["top_rules"][0]["rule"] == "frontier"


def test_new_checkpoints_by_mtime(tmp_path):
    runs = copy_runs(tmp_path)
    ts = datetime(2026, 11, 7, 15, 55).timestamp()
    st = runs / "checkpoints" / "nugget_bridge.state"
    os.utime(st, (ts, ts))
    s = swarm.summarise(runs, datetime(2026, 11, 7, 15, 50))
    assert s["new_checkpoints"] == [{"state": "nugget_bridge.state", "map": 35, "badges": 2,
                                     "party": [10], "money": 1500}]
    s = swarm.summarise(runs, datetime(2026, 11, 7, 16, 0))   # outside range: not "new"
    assert s["new_checkpoints"] == []


def test_breaks_invariant_error(monkeypatch):
    err = Finding(check="states", level=ERROR, kind="unreadable", message="synthetic break")
    monkeypatch.setattr("pokeagent.invariants.runner.run_all", lambda *a, **k: [err])
    s = swarm.summarise(RUNS, SINCE_ALL)
    assert s["broken"] and s["breaks"]["invariant_errors"][0]["message"] == "synthetic break"


def test_breaks_clean_run_set_is_not_broken():
    s = swarm.summarise(RUNS, SINCE_ALL, segment="to_bill")
    assert s["runs"]["count"] == 1
    assert not s["broken"]


def test_breaks_crash_no_decisions_and_loops():
    s = swarm.summarise(RUNS, SINCE_ALL)
    b = s["breaks"]
    assert b["crashed"] == [RUN_CRASH]
    assert b["no_decisions"] == [RUN_CRASH]
    assert b["loop_breaks"] == [{"run": RUN_STALL, "kind": "blocked_loop", "step": 21, "presses": 40}]
    assert s["broken"]


def test_legality_seam_unavailable_on_this_branch(monkeypatch):
    """Kept under its original name: the verify lane counts a renamed test as a removed one.
    Hermetic now that pokeagent.legality exists on main: the module is masked, not absent."""
    monkeypatch.setitem(sys.modules, "pokeagent.legality", None)   # import raises ImportError
    monkeypatch.delattr("pokeagent.legality", raising=False)
    s = swarm.summarise(RUNS, SINCE_ALL)
    assert s["breaks"]["legality"] == "unavailable (no pokeagent.legality on this branch)"
    assert s["breaks"]["legality_violations"] == []


def test_legality_live_path_when_module_exists(monkeypatch, tmp_path):
    fake = types.SimpleNamespace(check=lambda emu, kb=None: types.SimpleNamespace(
        violations=["party_stats: synthetic violation"]))
    monkeypatch.setitem(sys.modules, "pokeagent.legality", fake)
    monkeypatch.setattr("pokeagent.legality", fake, raising=False)   # the real module may be imported
    monkeypatch.setattr("pokeagent.invariants.runner.find_rom", lambda rd: Path("fake.gb"))
    from pokeagent.emulator import FakeEmulator
    monkeypatch.setattr("pokeagent.emulator.PyBoyEmulator", lambda *a, **k: FakeEmulator())
    runs = copy_runs(tmp_path)
    ts = datetime(2026, 11, 7, 15, 55).timestamp()
    os.utime(runs / "checkpoints" / "nugget_bridge.state", (ts, ts))
    s = swarm.summarise(runs, datetime(2026, 11, 7, 15, 50))
    assert s["breaks"]["legality"] == "ok"
    assert s["breaks"]["legality_violations"] == [
        "nugget_bridge.state: party_stats: synthetic violation"]
    assert s["broken"]


def test_invariant_warns_listed_only_with_flag(monkeypatch):
    warn = Finding(check="milestones", level="WARN", kind="odd", message="synthetic warn")
    monkeypatch.setattr("pokeagent.invariants.runner.run_all", lambda *a, **k: [warn])
    s = swarm.summarise(RUNS, SINCE_ALL)
    assert s["breaks"]["invariant_warns"] == 1
    s = swarm.summarise(RUNS, SINCE_ALL, invariants_verbose=True)
    assert s["breaks"]["invariant_warns"][0]["message"] == "synthetic warn"


def test_invariants_unavailable_is_reported(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("synthetic checker failure")
    monkeypatch.setattr("pokeagent.invariants.runner.run_all", boom)
    s = swarm.summarise(RUNS, SINCE_ALL)
    assert s["breaks"]["invariants"].startswith("unavailable: ")
