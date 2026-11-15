"""compare: does a candidate game's map memory agree with the baseline's?

Ported from the 2026-11-08 Red-vs-Blue scratch script: over the map ids present in BOTH files it
counts tile overlap, warp agreement, stationary-NPC agreement, and the suspect-wall split
(``ledge_exact`` / ``ledge_row`` / ``plain`` via ``ledges.classify_wall``). Pure counting - pass/fail
thresholds belong to the compat check, not here.
"""
from __future__ import annotations

import json

from pokeagent.brain.common import DIRS, mid_key
from pokeagent.brain.ledges import classify_wall, parse_edge


def _empty() -> dict:
    return {"tiles": {"candidate": 0, "overlap": 0, "candidate_only": 0},
            "warps": {"common": 0, "different": 0, "candidate_only": 0},
            "npcs": {"candidate": 0, "overlap": 0},
            "walls": {"baseline_walls": 0, "suspect": 0, "ledge_exact": 0, "ledge_row": 0,
                      "plain": 0, "unexplained": 0, "malformed": 0}}


def _tiles(m: dict) -> set:
    return set(m.get("visited") or {})


def _warp_keys(m: dict) -> dict:
    """Warp key -> canonical destination string (a list-shaped ``warps`` table keys on its dump)."""
    w = m.get("warps") or {}
    if isinstance(w, dict):
        return {k: json.dumps(v, sort_keys=True)[:80] for k, v in w.items()}
    return {json.dumps(x, sort_keys=True)[:80]: "" for x in w}


def _static_npcs(m: dict) -> set:
    """Stationary NPCs (``moves`` falsy, ``last`` present) as ``(pic, tuple(last))`` pairs."""
    out = set()
    for n in (m.get("npcs") or {}).values():
        if isinstance(n, dict) and not n.get("moves") and n.get("last"):
            try:
                out.add((n.get("pic"), tuple(n["last"])))
            except TypeError:
                continue
    return out


def _walls(baseline_map: dict, candidate_tiles: set) -> dict:
    """Baseline ``blocked`` edges the candidate stood on both ends of, split by ledge explanation."""
    walls = {"baseline_walls": 0, "suspect": 0, "ledge_exact": 0, "ledge_row": 0,
             "plain": 0, "unexplained": 0, "malformed": 0}
    for edge in set(baseline_map.get("blocked") or {}):
        walls["baseline_walls"] += 1
        try:
            x, y, d = parse_edge(edge)
        except ValueError:
            walls["malformed"] += 1
            walls["plain"] += 1  # a wall record that cannot be parsed is unexplained
            continue
        dx, dy = DIRS[d]
        if f"{x},{y}" in candidate_tiles and f"{x + dx},{y + dy}" in candidate_tiles:
            walls["suspect"] += 1
            walls[classify_wall(baseline_map, edge)] += 1
    walls["unexplained"] = walls["plain"]
    return walls


def _row(baseline_map: dict, candidate_map: dict) -> dict:
    baseline_map = baseline_map if isinstance(baseline_map, dict) else {}
    candidate_map = candidate_map if isinstance(candidate_map, dict) else {}
    bt, rt = _tiles(candidate_map), _tiles(baseline_map)
    bw, rw = _warp_keys(candidate_map), _warp_keys(baseline_map)
    common = set(bw) & set(rw)
    bn, rn = _static_npcs(candidate_map), _static_npcs(baseline_map)
    return {"tiles": {"candidate": len(bt), "overlap": len(bt & rt), "candidate_only": len(bt - rt)},
            "warps": {"common": len(common),
                      "different": sum(1 for k in common if bw[k] != rw[k]),
                      "candidate_only": len(set(bw) - set(rw))},
            "npcs": {"candidate": len(bn), "overlap": len(bn & rn)},
            "walls": _walls(baseline_map, bt)}


def _mid_out(mid):
    try:
        return int(mid)
    except (TypeError, ValueError):
        return mid


def compare_memory(baseline: dict, candidate: dict) -> dict:
    """Per-map rows and totals over the shared map ids; the module judges nothing."""
    bm = (baseline or {}).get("maps") or {}
    cm = (candidate or {}).get("maps") or {}
    shared = sorted(set(bm) & set(cm), key=mid_key)
    totals, rows = _empty(), []
    for mid in shared:
        row = _row(bm[mid], cm[mid])
        for sect in totals:
            for k in totals[sect]:
                totals[sect][k] += row[sect][k]
        rows.append((mid, row))
    rows.sort(key=lambda t: (-t[1]["walls"]["unexplained"], -t[1]["tiles"]["candidate_only"],
                             mid_key(t[0])))
    return {"totals": totals,
            "rows": [{"map": _mid_out(mid), **row} for mid, row in rows[:10]],
            "shared_maps": len(shared)}
