"""--headless must run with no tkinter at all (hard rule: headless never opens a window - and the
hidden mainloop it used to pay for was ~16% of the baseline profile)."""
from __future__ import annotations

import ast
import queue
import sys
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.headless_loop import LogRing, run
from pokeagent.explorer.memory import MapMemory

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _ctx(tmp_path) -> ExplorerContext:
    return ExplorerContext(emu=FakeEmulator({0xD35E: 0x28, 0xD362: 5, 0xD361: 6}),
                           mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(headless=True),
                           run_dir=tmp_path)


class _Engine:
    """Counts steps like Engine.step and marks the run done at the cap."""

    def __init__(self, ctx, until: int) -> None:
        self.ctx, self.until = ctx, until

    def step(self) -> None:
        self.ctx.step += 1
        if self.ctx.step >= self.until:
            self.ctx.done = True


def test_headless_loop_runs_with_no_tkinter(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)  # any import attempt raises ImportError
    ctx = _ctx(tmp_path)
    exits = []
    run(ctx, _Engine(ctx, 3), jobs=queue.Queue(), on_exit=lambda: None,
        exit_fn=lambda code=0: exits.append(code))
    assert exits == [0] and ctx.step == 3
    assert sys.modules.get("tkinter") is None  # the headless loop never touched Tk


def test_headless_loop_runs_queued_control_jobs(tmp_path):
    ctx = _ctx(tmp_path)
    jobs = queue.Queue()

    def job():
        return {"ok": True}

    from concurrent.futures import Future
    fut = Future()
    jobs.put((job, fut))
    run(ctx, _Engine(ctx, 1), jobs=jobs, on_exit=lambda: None, exit_fn=lambda code=0: None)
    assert fut.result(timeout=1) == {"ok": True}  # jobs still drain between ticks, off the socket thread


def test_log_ring_keeps_a_tail_and_writes_console_log(tmp_path):
    ring = LogRing(tmp_path / "console.log", tail=3)
    for i in range(5):
        ring(f"line {i}", "res")
    ring.close()
    assert list(ring.tail) == ["line 2", "line 3", "line 4"]
    assert (tmp_path / "console.log").read_text().count("line") == 5


def test_explore_demo_imports_without_tkinter(monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    sys.modules.pop("explore_demo", None)  # force a fresh import even if another test loaded it
    sys.path.insert(0, str(TOOLS))
    try:
        import explore_demo  # noqa: F401  -- would raise if it imported tkinter at module level
    finally:
        sys.path.remove(str(TOOLS))


def test_explore_demo_has_no_module_level_tkinter():
    """The Tk/PIL imports live inside the windowed branch: nothing Tk loads at module level."""
    tree = ast.parse((TOOLS / "explore_demo.py").read_text(encoding="utf-8"))
    bad = []
    for node in tree.body:  # module-level statements only
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name == "tkinter"]
        elif isinstance(node, ast.ImportFrom) and node.module in ("tkinter", "PIL", "_tkinter"):
            bad.append(node.module)
    assert not bad
