"""Standalone scripted-input runner for glitch probes.

A script is plain data (a list of dicts, so it can live in JSON). One action per step: a
``press`` list of Button names, a ``wait`` of frames, a ``mark`` (trace row only), or ``until``
+ ``press`` (repeat the presses until a RAM byte matches or the step's press cap is hit).
``run_script`` drives the Emulator seam and appends one :class:`Trace` row per step - buttons
only, it never writes memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from pokeagent.emulator import Button

MAX_PRESSES_PER_STEP = 40   # same ceiling the procedure runner gives a buttons action
MAX_WAIT_FRAMES = 3000
MAX_TOTAL_PRESSES = 400     # whole-script press budget; hitting it ends the run aborted:"budget"

_STEP_KEYS = {"id", "press", "hold", "settle", "wait", "mark", "until", "max_presses", "placeholder"}
_UNTIL_KEYS = {"addr", "equals"}


class Trace(TypedDict, total=False):
    """One ``run_script`` row: step index/id, the emulator frame and cumulative press count,
    the probe dict under ``ram``, ``reached`` for until steps and ``aborted`` on the last row."""

    i: int
    id: str
    frames: int | None
    presses: int
    ram: dict
    reached: bool | None
    aborted: str


@dataclass(frozen=True)
class Step:
    """One script step. ``until`` is (addr, equals); ``placeholder`` marks a step whose presses
    the controller still has to fill in (refused by run_recipe unless explicitly allowed)."""

    id: str
    press: tuple[Button, ...] = ()
    hold: int = 8
    settle: int = 16
    wait: int | None = None
    mark: bool = False
    until: tuple[int, int] | None = None
    max_presses: int = MAX_PRESSES_PER_STEP
    placeholder: bool = False


def _button(name) -> Button:
    try:
        return Button[str(name)]
    except KeyError:
        raise ValueError(f"unknown button {name!r}") from None


def _until(raw) -> tuple[int, int]:
    if not isinstance(raw, dict) or set(raw) - _UNTIL_KEYS or "addr" not in raw or "equals" not in raw:
        raise ValueError(f"until must be {{addr, equals}}: {raw!r}")
    addr = int(raw["addr"], 0) if isinstance(raw["addr"], str) else int(raw["addr"])
    want = int(raw["equals"])
    if not (0 <= want <= 0xFF):
        raise ValueError(f"until equals must be a byte: {raw!r}")
    return addr, want


def _step(raw) -> Step:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise ValueError(f"bad step: {raw!r}")
    unknown = set(raw) - _STEP_KEYS
    if unknown:
        raise ValueError(f"{raw['id']}: unknown step keys {sorted(unknown)}")
    press = tuple(_button(n) for n in raw.get("press") or ())
    if len(press) > MAX_PRESSES_PER_STEP:
        raise ValueError(f"{raw['id']}: {len(press)} presses > MAX_PRESSES_PER_STEP")
    wait = raw.get("wait")
    if wait is not None:
        wait = int(wait)
        if wait > MAX_WAIT_FRAMES:
            raise ValueError(f"{raw['id']}: wait {wait} > {MAX_WAIT_FRAMES} frames")
    mark = bool(raw.get("mark", False))
    until = _until(raw["until"]) if raw.get("until") is not None else None
    if until is not None:
        if not press:
            raise ValueError(f"{raw['id']}: until needs a press list to repeat")
        if wait is not None or mark:
            raise ValueError(f"{raw['id']}: until cannot combine with wait/mark")
    elif sum((bool(press), wait is not None, mark)) > 1:
        raise ValueError(f"{raw['id']}: one action per step (press, wait or mark)")
    return Step(id=raw["id"], press=press, hold=int(raw.get("hold", 8)), settle=int(raw.get("settle", 16)),
                wait=wait, mark=mark, until=until, max_presses=int(raw.get("max_presses", MAX_PRESSES_PER_STEP)),
                placeholder=bool(raw.get("placeholder", False)))


def load_script(data) -> list[Step]:
    """Step list from plain JSON-able rows; ValueError on a non-list or any malformed row."""
    if not isinstance(data, list):
        raise ValueError("a script is a list of step dicts")
    return [_step(d) for d in data]


def run_script(emu, steps, probes, *, record=None) -> list[Trace]:
    """Run ``steps`` against ``emu``; after every step call ``probes(emu) -> dict`` and append a
    Trace row. ``record`` (optional) is called with each row as it lands, for JSONL streaming.
    Read-only: presses and ticks only, never ``emu.write``. A run that hits MAX_TOTAL_PRESSES
    ends early; its last row carries ``aborted: "budget"``."""
    rows: list[Trace] = []
    presses = 0
    for i, step in enumerate(steps):
        reached = None
        aborted = presses >= MAX_TOTAL_PRESSES
        if aborted:
            pass
        elif step.until is not None:
            addr, want = step.until
            left = step.max_presses
            reached = emu.read(addr) == want
            while not reached and left > 0 and presses < MAX_TOTAL_PRESSES:
                for b in step.press:
                    emu.press(b, hold_frames=step.hold, settle_frames=step.settle)
                    presses += 1
                    left -= 1
                    if left <= 0 or presses >= MAX_TOTAL_PRESSES:
                        break
                if emu.read(addr) == want:
                    reached = True
            aborted = not reached and presses >= MAX_TOTAL_PRESSES
        elif step.wait is not None:
            emu.tick(step.wait)
        else:  # press list or a plain mark step (no action)
            for b in step.press:
                if presses >= MAX_TOTAL_PRESSES:
                    aborted = True
                    break
                emu.press(b, hold_frames=step.hold, settle_frames=step.settle)
                presses += 1
        row: Trace = {"i": i, "id": step.id, "frames": getattr(emu, "frames", None),
                      "presses": presses, "ram": probes(emu), "reached": reached}
        if aborted:
            row["aborted"] = "budget"
        rows.append(row)
        if record is not None:
            record(row)
        if aborted:
            break
    return rows
