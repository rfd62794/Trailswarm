"""_exit_headless cleanup isolation: a raising shutdown(ctx) must not skip close_logs(),
emu.close() or ctl.stop() - the console.log drain has to run on every exit path."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import explore_demo  # noqa: E402


def test_every_cleanup_runs_when_shutdown_raises():
    calls = []

    def record(name):
        def fn():
            calls.append(name)
        return fn

    def boom():
        calls.append("shutdown")
        raise RuntimeError("shutdown failed")

    explore_demo._run_exit_cleanups([
        record("close_frame_shm"), boom, record("close_logs"), record("emu.close"), record("ctl.stop"),
    ])
    assert calls == ["close_frame_shm", "shutdown", "close_logs", "emu.close", "ctl.stop"]


def test_all_cleanups_run_when_every_step_raises():
    calls = []

    def boom(name):
        def fn():
            calls.append(name)
            raise RuntimeError(name)
        return fn

    explore_demo._run_exit_cleanups([boom("a"), boom("b"), boom("c")])
    assert calls == ["a", "b", "c"]  # each failure is swallowed, none stops the rest
