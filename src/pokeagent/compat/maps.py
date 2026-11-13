"""Minimal map-memory comparison for the compat check (stand-in for brain/compare.compare_memory).

Same contract as the directive: counts over the map ids present in BOTH docs, wall suspects split into
ledge_exact / ledge_row (heuristic) / plain ("unexplained"). Docs are ``{"maps": {id: map}}``.
"""
from __future__ import annotations

from pokeagent.compat.ledges import classify_wall, parse_edge

_D = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def _static_npcs(m: dict) -> set:
    return {(n.get("pic"), tuple(n["last"])) for n in (m.get("npcs") or {}).values()
            if isinstance(n, dict) and not n.get("moves") and n.get("last")}


def _row(mid: str, b: dict, c: dict) -> dict:
    bt, ct = set(b.get("visited") or {}), set(c.get("visited") or {})
    bw, cw = b.get("warps") or {}, c.get("warps") or {}
    common = set(bw) & set(cw)
    bn, cn = _static_npcs(b), _static_npcs(c)
    walls = {"suspect": 0, "ledge_exact": 0, "ledge_row": 0, "plain": 0, "malformed": 0}
    blocked = list(b.get("blocked") or [])
    for e in blocked:
        try:
            x, y, d = parse_edge(e)
        except ValueError:
            walls["malformed"] += 1
            continue
        dx, dy = _D[d]
        if f"{x},{y}" in ct and f"{x + dx},{y + dy}" in ct:
            walls["suspect"] += 1
            walls[classify_wall(b, e)] += 1
    return {"map": mid, "tiles": len(ct), "overlap": len(ct & bt), "candidate_only": len(ct - bt),
            "warps_common": len(common), "warps_different": sum(1 for k in common if bw[k] != cw[k]),
            "warps_candidate_only": len(set(cw) - set(bw)), "npc_candidate": len(cn), "npc_match": len(cn & bn),
            "baseline_walls": len(blocked), **{f"walls_{k}": v for k, v in walls.items()},
            "unexplained": walls["plain"]}


def compare_memory(baseline: dict, candidate: dict) -> dict:
    bm, cm = baseline.get("maps") or {}, candidate.get("maps") or {}
    shared = sorted(set(bm) & set(cm), key=lambda k: (len(k), k))
    rows = [_row(m, bm[m], cm[m]) for m in shared]
    totals = {k: sum(r[k] for r in rows) for k in rows[0] if k != "map"} if rows else {}
    worst = sorted(rows, key=lambda r: (-r["unexplained"], -r["candidate_only"]))[:10]
    return {"shared_maps": len(shared), "totals": totals, "worst": worst}
