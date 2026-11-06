"""Macro runner: a macro is a step function over the screen. It reads before EVERY press and stops, never guesses.

``step(scr, st, rig) -> Step``: press a button, wait some frames, finish (``done``) or stop (``stop``, with a result code
such as ``unexpected_screen``). ``st`` is the macro's own scratch dict. The runner caps presses and consecutive waits and
returns ``{ok, result, presses, final_screen}``; ``trail`` lists the buttons pressed. The ``rig`` supplies ``emu``, ``read()``,
``press(button, why)`` and ``tick(frames)`` (EmuRig in production, a scripted fake in tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

DEFAULT_CAP = 40
MAX_WAITS = 8


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


def run_steps(step: StepFn, rig, name: str, cap: int = DEFAULT_CAP) -> dict:
    st: dict = {}
    presses, waits, trail = 0, 0, []

    def finish(ok: bool, result: str) -> dict:
        return {"ok": ok, "result": result, "presses": presses, "trail": trail, "final_screen": rig.read().brief()}

    while True:
        s = step(rig.read(), st, rig)
        if s.done:
            return finish(True, s.done)
        if s.stop:
            return finish(False, s.stop)
        if s.wait or not s.button:
            waits += 1
            if waits > MAX_WAITS:
                return finish(False, "screen_not_ready")
            rig.tick(max(1, s.wait))
            continue
        if presses >= cap:
            return finish(False, "press_cap")
        rig.press(s.button, f"{name}: {s.note or s.button}")
        presses += 1
        waits = 0
        trail.append(s.button)
