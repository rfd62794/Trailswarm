"""Check 4: every split cut point in segments.json lies on the route between the segment's start and end goals.

A segment for goal G runs from G's predecessor (campaign ``after``) to G. Its route is the set of maps the recorded attempts
at G actually passed through (stats.G.attempts[].maps) plus G's own detector map(s). A cut on any other map, or on an id
the ROM has no header for, is wrong. Ids print in decimal and hex: checkpoint names use hex ('@61' is map 97).
"""
from __future__ import annotations

from pathlib import Path

from pokeagent.invariants.findings import ERROR, INFO, Finding, fmt_map, read_json


def route_maps(stats_for_goal: dict, spec: dict | None) -> set[int]:
    seen = {m for a in (stats_for_goal or {}).get("attempts", []) for m in (a.get("maps") or []) if isinstance(m, int)}
    det = (spec or {}).get("detector")
    if isinstance(det, dict) and isinstance(det.get("map"), list):
        seen |= set(det["map"])
    return seen


def check_segments(runs_dir: Path, valid_ids: frozenset[int] | None = None) -> list[Finding]:
    from pokeagent import campaign
    data, err = read_json(runs_dir / "segments.json")
    if err or not isinstance(data, dict):
        return [Finding("segments", ERROR if err else INFO, "unreadable", f"segments.json: {err or 'missing or not an object'}")]
    splits, stats = data.get("splits") or {}, data.get("stats") or {}
    out: list[Finding] = []
    for goal, cuts in splits.items():
        spec = campaign.goal_spec(goal)
        if spec is None:
            out.append(Finding("segments", ERROR, "unknown_goal", f"split for unknown goal {goal!r}", {"goal": goal}))
            continue
        route = route_maps(stats.get(goal), spec)
        for cut in cuts:
            if not isinstance(cut, int) or isinstance(cut, bool):
                out.append(Finding("segments", ERROR, "bad_cut", f"{spec.get('after')} -> {goal}: cut {cut!r} is not an integer map id",
                                   {"goal": goal, "cut": cut}))
                continue
            where = f"{spec.get('after')} -> {goal}: cut map {fmt_map(cut)}"
            if valid_ids is not None and cut not in valid_ids:
                out.append(Finding("segments", ERROR, "bad_cut", f"{where} has no ROM header", {"goal": goal, "cut": cut}))
            elif not route:
                out.append(Finding("segments", INFO, "no_route_evidence", f"{where}: no attempts to judge it by", {"goal": goal, "cut": cut}))
            elif cut not in route:
                out.append(Finding("segments", ERROR, "bad_cut",
                                   f"{where} is not on the route; maps seen: " + ", ".join(fmt_map(m) for m in sorted(route)),
                                   {"goal": goal, "cut": cut, "route": sorted(route)}))
    return out
