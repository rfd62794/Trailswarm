"""Macro runner: a macro is a step function over the screen. It reads before EVERY press and stops, never guesses.

``step(scr, st, rig) -> Step``: press a button, wait some frames, finish (``done``) or stop (``stop``, with a result code
such as ``unexpected_screen``). ``st`` is the macro's own scratch dict. A ``MacroRun`` advances ONE step per ``advance()``
call, so the agent's frame loop can drive it a tick at a time (frames keep publishing, the snapshot keeps refreshing);
``run_steps`` just loops it for tests and scripts. Presses and consecutive waits are capped, a wall-clock deadline ends a
run that is merely slow, and ``cancel()`` ends it at the next step. The result is ``{ok, result, presses, trail,
final_screen}``. The ``rig`` supplies ``emu``, ``read()``, ``press(button, why)`` and ``tick(frames)``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_CAP = 40
MAX_WAITS = 8
DEADLINE_S = 60.0


class MacroArgError(ValueError):
    """Bad or missing macro arguments (reported as result ``bad_args``, nothing is pressed)."""


@dataclass
class Step:
    button: str = ""
    wait: int = 0     # frames to let pass before reading again
    done: str = ""    # finished: the result code
    stop: str = ""    # gave up: the result code (the screen was not what the macro expects)
    note: str = ""


StepFn = Callable[..., Step]


def press(button: str, note: str = "") -> Step:
    return Step(button=button, note=note)


class MacroRun:
    def __init__(self, step: StepFn, rig, name: str, cap: int = DEFAULT_CAP, deadline_s: float = DEADLINE_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.step, self.rig, self.name, self.cap, self._clock = step, rig, name, cap, clock
        self.st: dict = {}
        self.presses = self.waits = 0
        self.trail: list[str] = []
        self.started = clock()
        self.deadline = self.started + deadline_s
        self.result: dict | None = None
        self.finished = threading.Event()
        self._cancel = False

    @classmethod
    def failed(cls, name: str, result: str) -> "MacroRun":
        run = cls(lambda *a: Step(), None, name)
        run.result = {"ok": False, "result": result, "presses": 0}
        run.finished.set()
        return run

    @property
    def done(self) -> bool:
        return self.result is not None

    def cancel(self) -> None:
        self._cancel = True

    def _finish(self, ok: bool, result: str) -> None:
        try:
            screen = self.rig.read().brief()
        except Exception:
            screen = {}
        self.result = {"ok": ok, "result": result, "presses": self.presses, "trail": self.trail, "final_screen": screen}
        self.finished.set()

    def advance(self) -> bool:
        """Do one step (one screen read and at most one press or wait). True once the macro has finished."""
        if self.done:
            return True
        if self._cancel:
            self._finish(False, "cancelled")
        elif self._clock() > self.deadline:
            self._finish(False, "deadline")
        else:
            self._advance()
        return self.done

    def _advance(self) -> None:
        s = self.step(self.rig.read(), self.st, self.rig)
        if s.done:
            return self._finish(True, s.done)
        if s.stop:
            return self._finish(False, s.stop)
        if s.wait or not s.button:
            self.waits += 1
            if self.waits > MAX_WAITS:
                return self._finish(False, "screen_not_ready")
            return self.rig.tick(max(1, s.wait))
        if self.presses >= self.cap:
            return self._finish(False, "press_cap")
        self.rig.press(s.button, f"{self.name}: {s.note or s.button}")
        self.presses += 1
        self.waits = 0
        self.trail.append(s.button)

    def status(self) -> dict:
        r = self.result
        return {"name": self.name, "state": "running" if r is None else ("done" if r["ok"] else "stopped"),
                "result": r["result"] if r else "", "presses": self.presses,
                "age_s": round(self._clock() - self.started, 1)}


def run_steps(step: StepFn, rig, name: str, cap: int = DEFAULT_CAP, **kw) -> dict:
    run = MacroRun(step, rig, name, cap, **kw)
    while not run.advance():
        pass
    return run.result
