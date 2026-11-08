"""Segment par: the exact frame cost of a multi-map segment from the ROM grids.

Split out of segment_grades (module size): ``par_for_best`` lazily imports seg_store (tools/) so this
module stays inside the package; callers arrange the path. Every helper returns None rather than
guessing: a leg whose entry/exit tile is unknown makes the whole par unknown.
"""
from __future__ import annotations

import json
from pathlib import Path


def segment_par(maps_path: list[int], entries_exits: list, grids) -> float | None:
    """Exact par of a multi-map segment: ``map_par`` per map traversed plus FRAME_WALK for each
    leaving press (every map but the last). None when any leg is unknown or the grids are absent."""
    if grids is None or not maps_path or len(entries_exits) != len(maps_path):
        return None
    from pokeagent.legs.grid import FRAME_WALK
    from pokeagent.legs.par import map_par
    total, last = 0.0, len(maps_path) - 1
    for i, (m, ee) in enumerate(zip(maps_path, entries_exits)):
        if ee is None:
            return None
        r = map_par(grids, m, ee[0], ee[1])
        if r is None:
            return None
        total += r[0] + (FRAME_WALK if i < last else 0.0)
    return total


def _jl(path: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def entries_exits_for(run_dir: Path, maps_path: list[int]) -> list:
    """(entry tile, exit tile) per map of a run's path, from its transitions.jsonl: the first tile
    seen on each map and, for every map but the last, the tile stood on when the press into the next
    map was made; for the last map the run's final position (the goal tile, approximately)."""
    trans = _jl(Path(run_dir) / "transitions.jsonl")
    entries: dict[int, tuple] = {}
    for r in trans:
        to = r.get("to")
        if to and len(to) >= 3 and to[0] not in entries:
            entries[to[0]] = (to[1], to[2])
    out = []
    for i, m in enumerate(maps_path):
        ent = entries.get(m)
        ex = None
        if ent is not None:
            if i == len(maps_path) - 1:
                last = [r["to"] for r in trans if r.get("to") and len(r["to"]) >= 3 and r["to"][0] == m]
                ex = (last[-1][1], last[-1][2]) if last else None
            else:
                nxt = maps_path[i + 1]
                row = next((r for r in trans if r.get("from") and r.get("to")
                            and len(r["from"]) >= 3 and len(r["to"]) >= 3
                            and r["from"][0] == m and r["to"][0] == nxt), None)
                ex = (row["from"][1], row["from"][2]) if row else None
        out.append((ent, ex) if ent is not None and ex is not None else None)
    return out


def par_for_best(root, st: dict, grids) -> float | None:
    """Par for a segment's accepted best: its run's map path and entry/exit tiles. None when the run
    or any leg is unknown - never guessed."""
    import seg_store as ss
    b = ss.accepted(st)
    run = (b or {}).get("run")
    att = next((a for a in st["attempts"] if a.get("run") == run and a["solved"] and a.get("maps")), None)
    rd = Path(root) / "runs" / run if run else None
    if att is None or rd is None or not rd.is_dir():
        return None
    return segment_par(att["maps"], entries_exits_for(rd, att["maps"]), grids)


def make_par_fn(root, grids):
    """``par_fn(seg, st)`` for grade_all over the ROM grids (or whatever ``grids`` resolves to)."""
    def par_fn(seg, st):
        return par_for_best(root, st, grids)
    return par_fn
