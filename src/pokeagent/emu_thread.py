"""A dedicated thread that owns the emulator: tick it, run posted commands.

SDL2 windows must be created and pumped on one thread, and Windows marks a
window "not responding" if its event loop stalls. So the emulator is built,
ticked and closed on this worker thread; every MCP tool call is posted to it
as a ``fn(emu)`` and its result (or exception) handed back through a Future.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import TypeVar

from pokeagent.emulator import Emulator

T = TypeVar("T")


class EmulatorThread:
    """Owns one Emulator on a worker thread; commands run between idle ticks.

    ``idle_fps`` is the tick rate while no command is running; 0 means no idle
    ticking at all, so the game only advances inside commands. ``paused``
    suspends idle ticking without stopping the command queue.
    """

    def __init__(self, factory: Callable[[], Emulator], *, idle_fps: int = 60) -> None:
        self._factory = factory
        self.idle_fps = idle_fps
        self.paused = False
        self._jobs: queue.Queue[tuple[Callable[[Emulator], T], Future]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._emu: Emulator | None = None
        self._stopping = threading.Event()

    @property
    def emulator(self) -> Emulator | None:
        """The emulator the thread built, or None until start() finishes."""
        return self._emu

    def start(self) -> None:
        """Spawn the thread; the factory runs inside it. Factory errors re-raise here."""
        if self._thread is not None:
            raise RuntimeError("EmulatorThread already started")
        ready: Future = Future()
        self._thread = threading.Thread(
            target=self._main, args=(ready,), name="pokeagent-emu", daemon=True
        )
        self._thread.start()
        ready.result()  # propagates any exception raised by the factory

    def call(self, fn: Callable[[Emulator], T], timeout: float = 30) -> T:
        """Post ``fn(emu)`` to the emulator thread and block for its result."""
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("EmulatorThread is not running")
        fut: Future = Future()
        self._jobs.put((fn, fut))
        return fut.result(timeout=timeout)

    def stop(self) -> None:
        """Signal the loop to exit, let it close the emulator, then join."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _main(self, ready: Future) -> None:
        try:
            self._emu = self._factory()
        except Exception as e:
            ready.set_exception(e)
            return
        ready.set_result(self._emu)
        frame_seconds = 1.0 / self.idle_fps if self.idle_fps > 0 else 0.0
        while not self._stopping.is_set():
            self._drain()
            if self.idle_fps > 0 and not self.paused:
                started = time.monotonic()
                self._emu.tick(1)
                delay = frame_seconds - (time.monotonic() - started)
                if delay > 0:
                    time.sleep(delay)
            else:
                time.sleep(0.001)  # stay responsive to posted commands
        self._emu.close()

    def _drain(self) -> None:
        """Run every queued command; exceptions go back to the caller, never kill the loop."""
        while True:
            try:
                fn, fut = self._jobs.get_nowait()
            except queue.Empty:
                return
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(self._emu))
            except Exception as e:
                fut.set_exception(e)
