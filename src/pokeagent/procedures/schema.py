"""Goal procedure schema: an ordered list of precondition / action / expected-effect steps, graded per step.

A procedure is the HTN/GOAP answer to "how do we build goal-focused agents": each step has a RAM predicate
that must hold BEFORE it runs (``pre``), a short action (a button script, a waypoint, a named behaviour call,
or a defined interaction), and a RAM predicate that must hold AFTER (``effect``). Procedures are learned from
the best organic runs or hand-seeded, stored under ``runs/procedures/<goal>.json`` (gitignored), and graded
after every attempt - never trusted blindly (store.py owns the downgrade/disable rules).
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERSION = 1
MAX_SCRIPT = 40  # a ``buttons`` action may hold at most this many presses (untuned first value)
GOTO_MAX_PRESSES = 80    # press budget of a goto/waypoint step (untuned first value, matches the seed format)
GOTO_MAX_FRAMES = 2400   # frame budget of a goto/waypoint step (untuned first value)
FIGHT_MAX_PRESSES = 200  # press budget of a fight_trainer step (untuned first value)
FIGHT_MAX_FRAMES = 6000  # frame budget of a fight_trainer step (untuned first value)


@dataclass
class Step:
    """One procedure step. ``pre``/``effect`` are predicate dicts (predicates.py), ``action`` a kind dict."""

    id: str
    action: dict = field(default_factory=dict)
    pre: dict = field(default_factory=dict)
    effect: dict = field(default_factory=dict)
    optional: bool = False
    ok: int = 0
    fail: int = 0
    max_presses: int = GOTO_MAX_PRESSES
    max_frames: int = GOTO_MAX_FRAMES


@dataclass
class Procedure:
    """A goal's learned script plus its grading record."""

    goal: str
    steps: list = field(default_factory=list)  # list[Step]
    source: str = "seed"                       # "seed" | "mined"
    attempts: int = 0
    successes: int = 0
    best_frames: int | None = None
    best_presses: int | None = None
    disabled: bool = False
    fail_streak: int = 0                       # consecutive failed attempts (store.DISABLE_AFTER disables)
    version: int = VERSION


_STEP_KEYS = ("id", "optional", "pre", "action", "effect", "ok", "fail", "max_presses", "max_frames")


def step_to_json(step: Step) -> dict:
    return {"id": step.id, "optional": step.optional, "pre": step.pre, "action": step.action,
            "effect": step.effect, "ok": step.ok, "fail": step.fail,
            "max_presses": step.max_presses, "max_frames": step.max_frames}


def step_from_json(data) -> Step | None:
    """One step from its JSON row; None when the row is malformed (a bad row fails the whole load)."""
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return None
    for key in ("pre", "action", "effect"):
        if not isinstance(data.get(key, {}), dict):
            return None
    try:
        return Step(data["id"], dict(data.get("action") or {}), dict(data.get("pre") or {}),
                    dict(data.get("effect") or {}), bool(data.get("optional", False)),
                    int(data.get("ok", 0)), int(data.get("fail", 0)),
                    int(data.get("max_presses", GOTO_MAX_PRESSES)), int(data.get("max_frames", GOTO_MAX_FRAMES)))
    except (TypeError, ValueError):
        return None


def to_json(proc: Procedure) -> dict:
    """The on-disk shape: version, goal, source, the grading record, then the step list."""
    return {"version": proc.version, "goal": proc.goal, "source": proc.source,
            "attempts": proc.attempts, "successes": proc.successes,
            "best_frames": proc.best_frames, "best_presses": proc.best_presses,
            "disabled": proc.disabled, "fail_streak": proc.fail_streak,
            "steps": [step_to_json(s) for s in proc.steps]}


def from_json(data) -> Procedure | None:
    """A Procedure from parsed JSON; None for a wrong version or any malformed field (never raises)."""
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("goal"), str):
        return None
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        return None
    steps = [step_from_json(s) for s in raw_steps]
    if any(s is None for s in steps):
        return None
    try:
        return Procedure(data["goal"], steps, str(data.get("source", "seed")),
                         int(data.get("attempts", 0)), int(data.get("successes", 0)),
                         data.get("best_frames"), data.get("best_presses"),
                         bool(data.get("disabled", False)), int(data.get("fail_streak", 0)))
    except (TypeError, ValueError):
        return None
