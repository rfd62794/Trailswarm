"""Procedure store: runs/procedures/<goal>.json load/save (atomic), grading, and the trust rules.

Grading (called at the END of each attempt, never mid-step): per-step ``ok``/``fail`` counters, and a
procedure-level ``attempts``/``successes`` with ``best_frames``/``best_presses`` kept when a full run beats
them. Never trusted blindly: a step with ``fail >= DOWNGRADE_FAILS`` and ``fail > ok`` is downgraded (the
runner skips it so exploration continues) until a later success resets it; ``DISABLE_AFTER`` consecutive
failed attempts set ``disabled`` for the rest of the run. ``load`` returns None for a missing, unreadable or
wrong-version file, and copies a committed seed (seeds/) on first use - it never raises.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pokeagent.procedures.predicates import check
from pokeagent.procedures.schema import Procedure, Step, from_json, to_json

PROC_ROOT = Path("runs") / "procedures"
SEED_ROOT = Path(__file__).resolve().parent / "seeds"
# Committed seeds are named by content, not goal id; each serves the goal ids listed here.
SEEDS = {"nugget_bridge": "nugget_bridge.json", "ss_anne_2f": "ss_anne_corridor.json",
         "rival_ss_anne": "ss_anne_corridor.json"}
DOWNGRADE_FAILS = 2  # a step with this many fails and fail > ok is skipped until a later success (untuned)
DISABLE_AFTER = 3    # consecutive failed attempts that disable a procedure for the rest of the run (untuned)


def load(goal: str, root=None) -> Procedure | None:
    """The procedure for ``goal`` from ``root`` (default runs/procedures/), or a copied seed. Never raises."""
    root = Path(root) if root is not None else PROC_ROOT
    path = root / f"{goal}.json"
    if not path.exists():
        seed = SEED_ROOT / SEEDS.get(goal, f"{goal}.json")
        if not seed.exists():
            return None
        try:
            proc = from_json(json.loads(seed.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
        if proc is None:
            return None
        try:
            save(proc, root)  # copied on first use; the copy keeps grading between runs
        except OSError:
            pass  # an unwritable store must not lose the attempt
        return proc
    try:
        return from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save(proc: Procedure, root=None) -> Path:
    """Atomic write (tmp + replace) into ``root`` (created on first save)."""
    root = Path(root) if root is not None else PROC_ROOT
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{proc.goal}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(to_json(proc), indent=1), encoding="utf-8")
    os.replace(tmp, out)
    return out


def grade(proc: Procedure, step_id: str | None = None, ok: bool = False, presses: int = 0, frames: int = 0) -> Procedure:
    """One grade event: a step outcome, or an attempt outcome when ``step_id`` is None."""
    if step_id is not None:
        step = next((s for s in proc.steps if s.id == step_id), None)
        if step is None:
            return proc
        if ok:
            step.ok += 1
            step.fail = 0  # a later success (even outside the runner) resets a downgraded step
        else:
            step.fail += 1
        return proc
    proc.attempts += 1
    if ok:
        proc.successes += 1
        proc.fail_streak = 0
        if presses and (proc.best_presses is None or presses < proc.best_presses):
            proc.best_presses = presses
        if frames and (proc.best_frames is None or frames < proc.best_frames):
            proc.best_frames = frames
    else:
        proc.fail_streak += 1
        proc.disabled = proc.disabled or proc.fail_streak >= DISABLE_AFTER
    return proc


def downgraded(step: Step) -> bool:
    """Skipped until a success resets it: enough fails and more fails than wins."""
    return step.fail >= DOWNGRADE_FAILS and step.fail > step.ok


def next_step(proc: Procedure, state: dict, log=None) -> Step | None:
    """The first step whose effect is not yet met and that is not downgraded."""
    return next((s for s in proc.steps if not check(s.effect, state, log) and not downgraded(s)), None)
