"""statelib.slow_cut: the slowest map transition across finished runs -> the slow-cut fallback point."""
import json

from pokeagent.statelib import slow_cut


def run(tmp_path, name, rows):
    d = tmp_path / name
    d.mkdir()
    (d / "transitions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def hop(step, frm, to):
    return {"step": step, "from": [frm, 0, 0], "to": [to, 0, 0], "moved": True}


def test_slowest_median_map_wins(tmp_path):
    # every run: enters map 20 at step 100, leaves for 30 at step 700, leaves 30 for 40 at 900
    rows = [hop(100, 10, 20), hop(700, 20, 30), hop(900, 30, 40)]
    dirs = [run(tmp_path, f"r{i}", rows) for i in range(3)]
    assert slow_cut.slowest_transition(dirs) == 20       # median cost 600 beats map 30's 200


def test_earlier_and_first_map_are_excluded(tmp_path):
    rows = [hop(100, 10, 20), hop(700, 20, 30), hop(900, 30, 40)]
    dirs = [run(tmp_path, f"r{i}", rows) for i in range(3)]
    assert slow_cut.slowest_transition(dirs, earlier={20}) == 30
    rows2 = [hop(900, 10, 20)]                            # all steps spent in the FIRST map
    dirs2 = [run(tmp_path, f"s{i}", rows2) for i in range(3)]
    assert slow_cut.slowest_transition(dirs2) is None     # 10 is first; 20 is entered but never left


def test_min_runs_required(tmp_path):
    rows = [hop(100, 10, 20), hop(700, 20, 30)]
    dirs = [run(tmp_path, f"r{i}", rows) for i in range(2)]
    assert slow_cut.slowest_transition(dirs) is None      # map 20 measured in only 2 runs
    dirs.append(run(tmp_path, "r2", rows))
    assert slow_cut.slowest_transition(dirs) == 20


def test_missing_and_malformed_logs_count_as_no_data(tmp_path):
    ok = run(tmp_path, "ok", [hop(100, 10, 20), hop(700, 20, 30)])
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "transitions.jsonl").write_text("{not json\n[1,2")
    none = tmp_path / "missing"
    assert slow_cut.slowest_transition([ok, bad, none]) is None    # only one run's data survives
    dirs = [ok, run(tmp_path, "x2", [hop(100, 10, 20), hop(700, 20, 30)]),
            run(tmp_path, "x3", [hop(100, 10, 20), hop(700, 20, 30)]), bad, none]
    assert slow_cut.slowest_transition(dirs) == 20
    assert slow_cut.slowest_transition([]) is None
    assert slow_cut.slowest_transition(None) is None
