"""Progress panel: segment strip cells (done/current/ahead), steps on this goal vs the record, a steps-per-goal sparkline."""
from __future__ import annotations

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import DIM, WARN, Line, span
from pokeagent.viewer.panels import steps

_DONE = "#5fa85f"
_AHEAD = "#3f444e"


def progress_lines(snap: AgentSnapshot) -> list[Line]:
    out: list[Line] = []
    if snap.goals:
        cells: Line = []
        for i, g in enumerate(snap.goals[:8]):  # S1..S8 map to the first eight campaign goals
            color = _DONE if g.status == "done" else WARN if g.status == "current" else _AHEAD
            cells.append(span(f"S{i + 1} ", color))
        out.append(cells)
    out.append([span(steps.steps_text(snap), WARN), span(f"   step {snap.step}", DIM)])
    spark = steps.sparkline(steps.goal_steps(snap))
    if spark:
        out.append([span("steps/goal ", DIM), span(spark, _DONE)])
    return out
