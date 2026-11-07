"""Progress panel: segment strip cells (done/current/ahead), 'seg N / rec M', step."""
from __future__ import annotations

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import DIM, TEXT, WARN, Line, plain, span

_DONE = "#5fa85f"
_AHEAD = "#3f444e"


def _seg_index(seg_id: str) -> str:
    """'S3' -> '3'; anything else (an RL tag, empty) shows as-is."""
    if seg_id.startswith("S") and seg_id[1:].isdigit():
        return seg_id[1:]
    return seg_id or "?"


def progress_lines(snap: AgentSnapshot) -> list[Line]:
    out: list[Line] = []
    if snap.goals:
        cells: Line = []
        for i, g in enumerate(snap.goals[:8]):  # S1..S8 map to the first eight campaign goals
            color = _DONE if g.status == "done" else WARN if g.status == "current" else _AHEAD
            cells.append(span(f"S{i + 1} ", color))
        out.append(cells)
    rec = snap.segment.record if snap.segment.record is not None else "—"
    out.append([span(f"seg {_seg_index(snap.segment.id)} ", WARN),
                span(f"/ rec {rec}    step {snap.step}", DIM)])
    return out
