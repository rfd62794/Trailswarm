"""The run's per-step .jsonl appends go through one buffered writer: lines are held until the
50-step cadence or close, so the hot path stops paying a write+flush per line."""
from __future__ import annotations

import json
import queue

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.decisions import DecisionLog
from pokeagent.explorer.headless_loop import LogRing, run
from pokeagent.explorer.jsonl_buf import JsonlBuffer
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.press import write_transition
from pokeagent.explorer.press_frame import PressFrame


def test_lines_held_until_cadence(tmp_path):
    buf = JsonlBuffer(every=50)
    w = buf.open(tmp_path / "t.jsonl")
    w.write('{"a":1}\n')
    w.flush()  # a no-op: the buffer owns the cadence, not the caller
    assert (tmp_path / "t.jsonl").read_text() == ""
    buf.tick(49)
    assert (tmp_path / "t.jsonl").read_text() == ""
    buf.tick(50)
    assert (tmp_path / "t.jsonl").read_text() == '{"a":1}\n'


def test_close_drains_every_open_file(tmp_path):
    buf = JsonlBuffer()
    a, b = buf.open(tmp_path / "a.jsonl"), buf.open(tmp_path / "b.jsonl")
    a.write("1\n")
    b.write("2\n")
    buf.close()
    assert (tmp_path / "a.jsonl").read_text() == "1\n"
    assert (tmp_path / "b.jsonl").read_text() == "2\n"


def test_same_path_shares_one_writer(tmp_path):
    buf = JsonlBuffer()
    assert buf.open(tmp_path / "x.jsonl") is buf.open(tmp_path / "x.jsonl")


def test_decision_log_writes_through_the_buffer(tmp_path):
    buf = JsonlBuffer(every=2)
    log = DecisionLog(tmp_path / "d.jsonl", fh=buf.open(tmp_path / "d.jsonl"))
    log.write({"step": 1, "button": "A"})
    assert (tmp_path / "d.jsonl").read_text() == ""  # buffered, not flushed per record
    buf.tick(2)
    assert json.loads((tmp_path / "d.jsonl").read_text())["step"] == 1
    log.write({"step": 2, "button": "B"})
    log.close()
    assert len((tmp_path / "d.jsonl").read_text().splitlines()) == 2


def test_write_transition_ticks_the_buffer(tmp_path):
    """A press writes its transitions line AND advances the shared 50-step cadence."""
    buf = JsonlBuffer(every=2)
    ctx = ExplorerContext(emu=FakeEmulator({0xD35E: 0x28, 0xD362: 5, 0xD361: 6}),
                          mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path)
    ctx.jsonl_buf = buf
    ctx.trans = buf.open(tmp_path / "transitions.jsonl")
    ctx.step = 1
    write_transition(ctx, PressFrame(name="UP", source="agent", why="t"))
    assert (tmp_path / "transitions.jsonl").read_text() == ""
    ctx.step = 2
    write_transition(ctx, PressFrame(name="UP", source="agent", why="t"))
    rows = (tmp_path / "transitions.jsonl").read_text().splitlines()
    assert len(rows) == 2 and json.loads(rows[0])["button"] == "UP"


def test_log_ring_drains_on_the_step_cadence_and_on_close(tmp_path):
    """console.log shares the buffer contract: lines are held in memory until the 50-step
    cadence (``tick``) or ``close`` - a write+flush per line is the cost being removed."""
    ring = LogRing(tmp_path / "console.log")
    ring("line 1", "res")
    assert (tmp_path / "console.log").read_text() == ""  # held, not written per line
    ring.tick(49)
    assert (tmp_path / "console.log").read_text() == ""
    ring.tick(50)
    assert (tmp_path / "console.log").read_text() == "line 1\n"
    ring("line 2", "res")
    ring.close()  # close drains whatever the cadence left buffered
    assert (tmp_path / "console.log").read_text() == "line 1\nline 2\n"


def test_crash_inside_the_loop_still_drains_the_tail(tmp_path):
    """The finding behind the try/finally: an exception inside run() must still run on_exit()
    (once), so every buffered line below the 50-step cadence reaches the disk - and the
    clean-path exit_fn does not fire on the way out."""
    buf, ring = JsonlBuffer(), LogRing(tmp_path / "console.log")
    ctx = ExplorerContext(emu=FakeEmulator({0xD35E: 0x28, 0xD362: 5, 0xD361: 6}),
                          mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(headless=True),
                          log=ring, run_dir=tmp_path)
    ctx.jsonl_buf = buf
    ctx.trans = buf.open(tmp_path / "transitions.jsonl")
    for i in range(5):  # five buffered lines: below the cadence, so nothing is on disk yet
        ctx.trans.write(f'{{"line": {i}}}\n')
    ctx.log("a console line", "res")
    assert (tmp_path / "transitions.jsonl").read_text() == ""
    assert (tmp_path / "console.log").read_text() == ""

    class _Boom:
        def tick(self):  # agent_view.tick is the first thing the loop does each iteration
            raise RuntimeError("crash inside the loop")

    exits, on_exit_calls = [], []
    with pytest.raises(RuntimeError):
        run(ctx, object(), jobs=queue.Queue(), agent_view=_Boom(),
            on_exit=lambda: (on_exit_calls.append(1), buf.close(), ring.close()),
            exit_fn=lambda code=0: exits.append(code))
    assert len((tmp_path / "transitions.jsonl").read_text().splitlines()) == 5
    assert (tmp_path / "console.log").read_text() == "a console line\n"
    assert on_exit_calls == [1] and exits == []  # on_exit ran once; exit_fn is clean-path only
