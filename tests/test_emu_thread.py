import threading
import time

import pytest

from pokeagent.emu_thread import EmulatorThread
from pokeagent.emulator import FakeEmulator


def make_thread(memory=None, idle_fps=0):
    """Start an EmulatorThread on a fresh FakeEmulator; returns (thread, emu)."""
    made = []

    def factory():
        emu = FakeEmulator(memory)
        made.append(emu)
        return emu

    thread = EmulatorThread(factory, idle_fps=idle_fps)
    thread.start()  # blocks until the factory ran on the worker thread
    return thread, made[0]


def test_call_runs_on_the_emulator_thread():
    thread, _ = make_thread()
    try:
        ident = thread.call(lambda emu: threading.get_ident())
        assert ident != threading.get_ident()
        assert ident == thread._thread.ident
    finally:
        thread.stop()


def test_call_returns_results_through_the_fake():
    thread, emu = make_thread({0xD362: 7})
    try:
        assert thread.call(lambda e: e.read(0xD362)) == 7
        assert thread.call(lambda e: (e.tick(5), e.frames)[1]) == 5
    finally:
        thread.stop()


def test_call_propagates_exceptions_and_the_thread_survives():
    thread, _ = make_thread()

    def boom(emu):
        raise ValueError("nope")

    try:
        with pytest.raises(ValueError, match="nope"):
            thread.call(boom)
        assert thread.call(lambda e: "still alive") == "still alive"
    finally:
        thread.stop()


def test_idle_ticks_when_fps_positive():
    thread, emu = make_thread(idle_fps=1000)
    try:
        deadline = time.monotonic() + 2
        while emu.frames == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert emu.frames > 0
    finally:
        thread.stop()


def test_no_idle_ticks_when_fps_zero():
    thread, emu = make_thread(idle_fps=0)
    try:
        time.sleep(0.05)
        assert emu.frames == 0
    finally:
        thread.stop()


def test_pause_stops_ticking_and_resume_restarts_it():
    thread, emu = make_thread(idle_fps=1000)
    try:
        deadline = time.monotonic() + 2
        while emu.frames == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        thread.paused = True
        time.sleep(0.02)  # let the loop observe the flag
        frozen = emu.frames
        time.sleep(0.05)
        assert emu.frames == frozen
        thread.paused = False
        time.sleep(0.05)
        assert emu.frames > frozen
    finally:
        thread.stop()


def test_stop_closes_the_fake_exactly_once():
    closes = []
    made = []

    def factory():
        emu = FakeEmulator()
        original = emu.close

        def counted():
            closes.append(1)
            original()

        emu.close = counted
        made.append(emu)
        return emu

    thread = EmulatorThread(factory, idle_fps=0)
    thread.start()
    thread.stop()
    thread.stop()  # a second stop is harmless
    assert closes == [1]
    assert made[0].closed
    assert not thread._thread.is_alive()


def test_call_before_start_raises():
    thread = EmulatorThread(FakeEmulator, idle_fps=0)
    with pytest.raises(RuntimeError, match="not running"):
        thread.call(lambda e: 1)


def test_factory_error_is_reraised_by_start():
    def factory():
        raise FileNotFoundError("no rom")

    thread = EmulatorThread(factory, idle_fps=0)
    with pytest.raises(FileNotFoundError, match="no rom"):
        thread.start()
