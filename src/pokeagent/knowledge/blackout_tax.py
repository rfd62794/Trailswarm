"""Blackout tax: each blackout against a stage raises the readiness margin that stage demands next time.

Robert (2026-11-07): "Should blacking out trend toward more leveling after?" Yes - the simulated duel is
optimistic where the real fight (items, crits, AI switches) is not, so the blackout count is the measured
correction: every blackout adds one step (0.10 of margin, capped at 4 steps / 0.40 extra), and only a won
TRAINER battle decays one step (wild wins are cheap and would erase the tax within a few steps).

The learned value lives in the shared memory dict (``ctx.mem.data``, saved to ``runs/maps.json`` by
``MapMemory.save``) as a top-level ``blackout_tax`` key::

    {"blackout_tax": {"rival_ss_anne": {"steps": 3}, "beat_misty": {"steps": 1}}}

The key of each entry is a stage goal exactly as ``training.stage_goal(goals)`` returns it (a key of
``TRAIN_LEVEL_BY_GOAL``); ``steps`` is an INTEGER - never a float; the margin is derived from it. A stage
with zero steps is removed from the dict. Same cross-process semantics as ``battle_lessons`` (read at
start, written by ``save``); no locking, no new file.
"""
from __future__ import annotations

TAX_STEP = 0.10          # margin added per blackout step
TAX_CAP = 0.40           # the most that can be added
MAX_STEPS = 4            # round(TAX_CAP / TAX_STEP)


def _table(data: dict, create: bool = False) -> dict:
    """The ``blackout_tax`` sub-dict of the shared learned data; a throwaway {} for a missing/malformed one."""
    t = data.get("blackout_tax") if isinstance(data, dict) else None
    if not isinstance(t, dict):
        if not create or not isinstance(data, dict):
            return {}
        data["blackout_tax"] = t = {}
    return t


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def steps(data: dict, goal: str) -> int:
    """Blackout steps recorded against `goal`, clamped to 0..MAX_STEPS; 0 for missing/malformed data."""
    e = _table(data).get(goal)
    return max(0, min(MAX_STEPS, _int(e.get("steps", 0)) if isinstance(e, dict) else 0))


def extra_margin(data: dict, goal: str) -> float:
    """The readiness-margin bonus `goal`'s steps add (0.0 when it has none)."""
    return round(steps(data, goal) * TAX_STEP, 2)


def extras(data: dict) -> dict[str, float]:
    """{goal: extra margin} for every goal with steps > 0 - the table ``training.set_blackout_tax`` takes."""
    return {g: round(steps(data, g) * TAX_STEP, 2) for g in _table(data) if steps(data, g) > 0}


def on_blackout(data: dict, goal: str) -> int:
    """Record a blackout at `goal`'s stage: one step more (to MAX_STEPS), creating the key. Returns the new steps."""
    n = min(steps(data, goal) + 1, MAX_STEPS)
    _table(data, create=True)[goal] = {"steps": n}
    return n


def on_win(data: dict, goal: str) -> int:
    """Decay `goal`'s tax by one step after a won trainer battle; the goal's entry is removed at 0. Returns the new steps."""
    n = max(steps(data, goal) - 1, 0)
    t = _table(data)
    if n:
        t[goal] = {"steps": n}
    else:
        t.pop(goal, None)
    return n


def merge_max(dst: dict, src: dict) -> None:
    """Fold `src`'s blackout tax into `dst` per goal, keeping the MAX of steps (every agent starts from the shared
    copy, so summing would count the base once per agent). Zero and malformed entries in `src` are dropped."""
    st = src.get("blackout_tax") if isinstance(src, dict) else None
    if not isinstance(st, dict):
        return
    for goal in st:
        n = steps(src, goal)
        if n <= 0:
            continue
        _table(dst, create=True)[goal] = {"steps": max(n, steps(dst, goal))}
