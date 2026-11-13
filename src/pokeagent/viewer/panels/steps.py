"""Steps on this goal vs the record, as text and a sparkline of steps per goal (pure)."""
from __future__ import annotations

from pokeagent.snapshot import AgentSnapshot

_LEVELS = "_.-=+*#"      # ASCII: every card font has these


def current(snap: AgentSnapshot) -> tuple[str, int, int | None]:
    """(goal name, steps on it, best steps so far) of the goal being worked on."""
    g = next((g for g in snap.goals if g.status == "current"), None)
    name = (g.name or g.id) if g else ""
    name = name or snap.segment.name or snap.segment.id or "?"
    steps = snap.segment.steps or (g.steps if g and g.steps else 0)
    return name, steps, snap.segment.record


def steps_text(snap: AgentSnapshot) -> str:
    """``beat_misty: 1,240 steps (best 980)``; ``(no record yet)`` while there is no best."""
    name, steps, best = current(snap)
    return f"{name}: {steps:,} steps ({'best ' + format(best, ',') if best is not None else 'no record yet'})"


def sparkline(values: list[int], width: int = 12) -> str:
    """The last ``width`` values scaled onto ASCII levels; '' when there is nothing to plot."""
    vals = [v for v in values if v is not None][-width:]
    if not vals:
        return ""
    top = max(vals) or 1
    return "".join(_LEVELS[min(len(_LEVELS) - 1, int(v / top * (len(_LEVELS) - 1) + 0.5))] for v in vals)


def goal_steps(snap: AgentSnapshot) -> list[int]:
    """Steps spent per finished goal, in campaign order, plus the current one."""
    out = [g.steps for g in snap.goals if g.status == "done" and g.steps]
    cur = current(snap)[1]
    return out + ([cur] if cur else [])
