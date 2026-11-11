"""The perf probe's bucketing, tested on a synthetic .prof fixture: every row lands in the
directive's bucket and the per-step call counts come out. (No ROMs/runs in a worktree, so the
probe itself cannot be run here - the fixture exercises the report path.)"""
from __future__ import annotations

import pstats
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import perf_probe  # noqa: E402


def _stats(entries) -> pstats.Stats:
    """A pstats.Stats with a synthetic .stats table: (filename, funcname, ncalls, tottime) rows."""
    st = pstats.Stats()
    st.stats = {(f, 1, fn): (nc, nc, tt, tt, {}) for f, fn, nc, tt in entries}
    return st


def _fixture() -> pstats.Stats:
    return _stats([
        ("C:/site-packages/pyboy/pyboy.py", "tick", 18634, 25.0),
        ("C:/repo/src/pokeagent/emulator.py", "tick", 18634, 3.9),
        ("C:/python312/lib/tkinter/__init__.py", "call", 25530, 18.0),
        ("C:/repo/src/pokeagent/explorer/world.py", "neighbours", 1936764, 15.0),
        ("C:/repo/src/pokeagent/explorer/world.py", "_bfs_node", 5480, 1.4),
        ("C:/repo/src/pokeagent/ramstructs.py", "read_party", 11320, 1.0),
        ("C:/python312/lib/json/__init__.py", "dumps", 5730, 0.8),
        ("C:/python312/lib/selectors.py", "select", 4000, 9.0),
        ("C:/repo/src/pokeagent/explorer/press.py", "log_press", 2000, 0.3),
        ("C:/other/thing.py", "work", 7, 0.5),
    ])


def test_buckets_match_the_baseline_shape():
    out = perf_probe.report(_fixture(), steps=2000, secs=111.6, presses=2000)
    rows = {ln.split("|")[1].strip(): ln for ln in out.splitlines() if ln.startswith("| ")}
    assert "PyBoy tick/emulation" in rows and "28.9 s" in rows["PyBoy tick/emulation"]
    assert "Tk GUI loop" in rows and "18.0 s" in rows["Tk GUI loop"]
    assert "decision logic" in rows  # world.py (16.4s) + press.py (0.3s) land here
    assert "16.7 s" in rows["decision logic"]
    assert "9.0 s" in rows["socket/select wait"]
    assert "0.8 s" in rows["file I/O / json"]
    assert "1.0 s" in rows["RAM/screen reads"]
    assert "steps/s=17.92" in out


def test_per_step_named_counts():
    out = perf_probe.report(_fixture(), steps=2000, secs=111.6)
    assert "read_party 5.66/step" in out
    assert "world._bfs_node 2.74/step" in out
    assert "world.neighbours 968.38/step" in out
    assert "json.dumps 2.87/step" in out


def test_report_only_reads_a_prof_file(tmp_path):
    prof = tmp_path / "x.prof"
    _fixture().dump_stats(str(prof))
    rc = perf_probe.main(["--report-only", str(prof), "--steps", "2000"])
    assert rc == 0
