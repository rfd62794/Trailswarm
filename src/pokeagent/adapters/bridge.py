"""Emulator-thread bridge: viewer HTTP handlers never touch the emulator themselves.

The agent's own loop calls ``tick()`` once per frame/step (on the emulator thread). That drains the
job queue (commands run here) and refreshes a cached snapshot every ``every`` ticks, so the
ControlServer thread only ever reads a finished, immutable snapshot or waits on a job result.
Layer rule: adapters/ never import viewer/.
"""
from __future__ import annotations

import queue
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any, Callable


class EmuBridge:
    def __init__(self, build: Callable[[], Any], *, every: int = 6, timeout: float = 2.0,
                 marshal: bool = True) -> None:
        self._build, self.every, self.timeout, self.marshal = build, max(1, every), timeout, marshal
        self.jobs: queue.Queue = queue.Queue()
        self._cache: Any = None
        self._n = 0

    # -- emulator thread -----------------------------------------------------------
    def refresh(self) -> Any:
        self._cache = self._build()
        return self._cache

    def pump(self) -> None:
        while True:
            try:
                fn, fut = self.jobs.get_nowait()
            except queue.Empty:
                return
            if not fut.set_running_or_notify_cancel():  # caller timed out: do not run it late
                continue
            try:
                fut.set_result(fn())
            except Exception as exc:
                fut.set_exception(exc)

    def tick(self) -> None:
        self.pump()
        self._n += 1
        if self._cache is None or self._n % self.every == 0:
            self.refresh()

    # -- HTTP threads ----------------------------------------------------------------
    def call(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` on the emulator thread; TimeoutError when the loop does not get to it."""
        fut: Future = Future()
        self.jobs.put((fn, fut))
        try:
            return fut.result(timeout=self.timeout)
        except FutureTimeout:
            fut.cancel()
            raise TimeoutError("emulator thread busy") from None

    def snapshot(self) -> Any:
        if not self.marshal:
            return self._build()
        cached = self._cache
        return cached if cached is not None else self.call(self.refresh)

    def wrap(self, handler: Callable[..., dict]) -> Callable[..., dict]:
        """Marshal a command handler onto the emulator thread; a snapshot refresh follows it."""
        if not self.marshal:
            return handler

        def run(**kw) -> dict:
            def job():
                out = handler(**kw)
                self.refresh()
                return out
            try:
                return self.call(job)
            except TimeoutError as exc:
                return {"error": str(exc)}
        return run
