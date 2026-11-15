"""The slow cut: where a long-or-stalling segment actually burns its steps.

Failure-driven splitting (tools/seg_split.cut_maps) cuts at maps reached by failed attempts; a segment that
SOLVES but does it slowly has no failed path to read. ``slowest_transition`` is the fallback for that case:
for each finished run's transitions.jsonl, a map's cost is the steps spent inside it before the next map
change, and the cut lands on the map with the highest MEDIAN cost per run - provided it is not the segment's
first map, not already inside an earlier segment, and was seen in at least MIN_RUNS runs. Reads are tolerant
in the style of seg_split._jl: a missing or malformed log counts as no data.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

MIN_RUNS = 3   # a map must appear in at least this many runs before its median cost is trusted (untuned)


def _jl(path) -> list:
    try:
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def _costs(run_dir) -> tuple[dict, int | None, set]:
    """(map -> steps spent before leaving, first map, visited maps) for one run's transitions.jsonl.
    A map transition is a record whose to[0] differs from from[0]; a position jump (state reload) opens a
    fresh interval. The last map visited never leaves, so it earns no cost."""
    cost: dict[int, float] = {}
    visited: set = set()
    cur_map, entry_step, first = None, 0, None
    for r in _jl(Path(run_dir) / "transitions.jsonl"):
        frm, to, step = r.get("from"), r.get("to"), r.get("step")
        if not (isinstance(frm, list) and frm and isinstance(to, list) and to
                and isinstance(step, (int, float)) and not isinstance(step, bool)):
            continue
        if first is None:
            first = frm[0]
        if cur_map != frm[0]:
            cur_map, entry_step = frm[0], step
        visited.add(frm[0])
        if to[0] != frm[0]:
            cost[frm[0]] = cost.get(frm[0], 0) + max(0, step - entry_step)
            cur_map, entry_step = to[0], step
            visited.add(to[0])
    return cost, first, visited


def slowest_transition(run_dirs, earlier=frozenset()) -> int | None:
    """The map id with the highest median per-run step cost, seen in at least MIN_RUNS runs, excluding maps
    in ``earlier`` and the segment's first map. ``None`` when no map qualifies (the caller retries later)."""
    per_map: dict[int, list] = {}
    seen: dict[int, int] = {}
    first = None
    for d in run_dirs or ():
        cost, f, visited = _costs(d)
        if first is None:
            first = f
        for m in visited:
            seen[m] = seen.get(m, 0) + 1
        for m, c in cost.items():
            per_map.setdefault(m, []).append(c)
    cands = [m for m in seen if seen[m] >= MIN_RUNS and m not in earlier and m != first and per_map.get(m)]
    if not cands:
        return None
    return min(cands, key=lambda m: (-statistics.median(per_map[m]), m))
