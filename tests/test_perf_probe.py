"""The perf probe's bucketing, tested on a synthetic .prof fixture: every row lands in the
directive's bucket and the per-step call counts come out. (No ROMs/runs in a worktree, so the
probe itself cannot be run here - the fixture exercises the report path.)"""
from __future__ import annotations

import os
import pstats
import queue
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import perf_probe  # noqa: E402
from pokeagent.emulator import FakeEmulator  # noqa: E402
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions  # noqa: E402
from pokeagent.explorer.headless_loop import run  # noqa: E402
from pokeagent.explorer.memory import MapMemory  # noqa: E402


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
        ("C:/repo/src/pokeagent/ramstructs.py", "read_party_count", 4000, 0.2),
        ("C:/repo/src/pokeagent/ramstructs.py", "_read_party", 5880, 0.9),
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
    assert "2.1 s" in rows["RAM/screen reads"]  # read_party + count + the real _read_party decode
    assert "steps/s=17.92" in out


def test_per_step_named_counts():
    out = perf_probe.report(_fixture(), steps=2000, secs=111.6)
    assert "read_party (wrapper) 5.66/step" in out
    assert "read_party_count (wrapper) 2.00/step" in out
    assert "_read_party (real) 2.94/step" in out
    assert "world._bfs_node 2.74/step" in out
    assert "world.neighbours 968.38/step" in out
    assert "json.dumps 2.87/step" in out


def test_real_work_rows_are_distinct_from_wrapper_rows():
    """The report must show wrapper call volume AND the real decode count side by side: the memo's
    effect is only visible when ``_read_party`` is counted separately from ``read_party``."""
    labels = [label for label, _needle, _func in perf_probe.COUNTS]
    assert "read_party (wrapper)" in labels and "_read_party (real)" in labels
    out = perf_probe.report(_fixture(), steps=2000, secs=111.6)
    assert "read_party (wrapper) 5.66/step" in out and "_read_party (real) 2.94/step" in out
    assert "world._bfs_node" in out and "world.neighbours" in out


def test_maps_option_copies_the_file_and_never_mutates_the_source(tmp_path):
    """``--maps`` seeds the run from a COPY inside the work dir: the learned memory the probe
    writes must land on the copy, leaving the seeded source byte-identical."""
    src = tmp_path / "seeded" / "maps.json"
    src.parent.mkdir()
    payload = '{"maps": {"1": {"visited": {"0,0": 1}}}}'
    src.write_text(payload, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    a = type("A", (), {"maps": str(src)})()
    dst = perf_probe._work_maps(a, work)
    assert dst == work / "maps.json" and dst != src
    assert dst.read_text(encoding="utf-8") == payload
    assert src.read_text(encoding="utf-8") == payload  # the source was only read
    # and with no --maps the work dir still gets a fresh empty memory
    empty = perf_probe._work_maps(type("A", (), {"maps": None})(), work)
    assert empty.read_text(encoding="utf-8") == '{"maps": {}}'


def test_report_only_reads_a_prof_file(tmp_path):
    prof = tmp_path / "x.prof"
    _fixture().dump_stats(str(prof))
    rc = perf_probe.main(["--report-only", str(prof), "--steps", "2000"])
    assert rc == 0


class _DoneEngine:
    """Counts steps like Engine.step and marks the run done at the cap."""

    def __init__(self, ctx, until: int) -> None:
        self.ctx, self.until = ctx, until

    def step(self) -> None:
        self.ctx.step += 1
        if self.ctx.step >= self.until:
            self.ctx.done = True


def test_run_returns_when_os_exit_is_trapped_after_import(tmp_path, monkeypatch):
    """The probe swaps ``os._exit`` for ``_trap_exit`` AFTER headless_loop was imported, so the
    default ``exit_fn`` must resolve ``os._exit`` at call time: run() reaches ctx.done, the trap
    fires, and control returns here to keep profiling (the bug killed the process before
    ``prof.dump_stats``)."""
    ctx = ExplorerContext(emu=FakeEmulator({0xD35E: 0x28, 0xD362: 5, 0xD361: 6}),
                          mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(headless=True),
                          run_dir=tmp_path)
    exits = []
    monkeypatch.setattr(os, "_exit", lambda code=0: exits.append(code))
    run(ctx, _DoneEngine(ctx, 3), jobs=queue.Queue())  # no exit_fn: the default must see the trap
    assert exits == [0] and ctx.step == 3  # the trapped exit fired and run() returned control
