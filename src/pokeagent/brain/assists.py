"""assists: how much human help one run directory got, and which goals it reached unaided.

Reads a run's ``transitions.jsonl`` presses (loaded by the CLI), its ``goal_frames.jsonl`` goal
firsts and ``meta.json`` ``initial_goals``. Assist presses are those whose ``source`` is ``human``
or ``claude`` (a press made by a person or by Claude through the control server); any other source
string is a non-assist driver. Nothing here copies dialogue or ``text`` fields into the report.
"""
from __future__ import annotations

from collections import Counter

ASSIST_SOURCES = ("human", "claude")


def _step(r: dict) -> int:
    s = r.get("step")
    return s if isinstance(s, int) and not isinstance(s, bool) else 0


def _press_map(t: dict):
    """The map the press was made on (``from`` first, ``to`` as fallback)."""
    for key in ("from", "to"):
        v = t.get(key)
        if isinstance(v, (list, tuple)) and v:
            return v[0]
    return None


def _stage(step: int, reached: list, initial: set, order: list) -> str:
    """First ladder goal that is neither initial nor reached at or before ``step`` (or "done")."""
    done = {g for g, s in reached if s <= step}
    return next((g for g in order if g not in initial and g not in done), "done")


def _clusters(assists: list, reached: list, initial: set, order: list, gap: int) -> list:
    """Consecutive assist presses grouped: a new cluster on a map change or a step gap > ``gap``."""
    out, cur = [], None
    for t in assists:
        m, s = _press_map(t), _step(t)
        same = cur is not None and m == cur["map"] and s - cur["step_end"] <= gap
        if not same:
            cur = {"map": m, "step_start": s, "step_end": s, "presses": 0,
                   "by_source": Counter(), "goal_stage": _stage(s, reached, initial, order),
                   "buttons": Counter()}
            out.append(cur)
        cur["presses"] += 1
        cur["step_end"] = s
        cur["by_source"][str(t["source"])] += 1
        cur["buttons"][str(t.get("button"))] += 1
    for c in out:
        c["by_source"] = dict(c["by_source"])
        c["buttons"] = dict(c["buttons"])
    return out


def _goal_ends(reached: list, assist_steps: list) -> list:
    """Per reached goal: how many assist presses happened inside its stage, and the unaided flag."""
    out, prev = [], 0
    for goal, step in reached:
        n = sum(1 for s in assist_steps if prev < s <= step)
        out.append({"goal": goal, "step": step, "assists_in_stage": n, "unaided": n == 0})
        prev = step
    return out


def assists_report(transitions: list, goal_frames: list, initial_goals: list,
                   goals_order: list, gap: int = 20) -> dict:
    """Pure report over one run's presses and goal firsts; no file IO, no verdict."""
    presses = [t for t in (transitions or []) if isinstance(t, dict)]
    reached = sorted(((r.get("goal"), _step(r)) for r in (goal_frames or [])
                      if isinstance(r, dict) and not r.get("skipped") and r.get("goal") is not None),
                     key=lambda p: p[1])
    initial = set(initial_goals or [])
    order = list(goals_order or [])
    assists = [t for t in presses if t.get("source") in ASSIST_SOURCES]
    goal_ends = _goal_ends(reached, [_step(t) for t in assists])
    end_step = max([_step(t) for t in presses] + [s for _, s in reached], default=0)
    return {"total_presses": len(presses),
            "by_source": dict(Counter(str(t.get("source", "agent")) for t in presses)),
            "assist_presses": len(assists),
            "clusters": _clusters(assists, reached, initial, order, gap),
            "goal_ends": goal_ends,
            "unaided_goals": [e["goal"] for e in goal_ends if e["unaided"]],
            "final_stage": _stage(end_step, reached, initial, order),
            "milestone_unaided": bool(goal_ends) and all(e["unaided"] for e in goal_ends)}
