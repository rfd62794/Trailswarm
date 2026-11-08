"""``summarise(RunData)`` - the dict ``pokeagent review run`` prints (text and --json share it)."""
from __future__ import annotations

from collections import Counter

from pokeagent.review.events import BUY_RULES, HEAL_RULES, build_events, is_reserved
from pokeagent.review.load import RunData
from pokeagent.review.loops import BREAK_LOOP_ROWS, LONG_LOOP_ROWS, collapse_loops, find_loops
from pokeagent.review.rules import top_rules

MAX_EVENTS = 200        # untuned first value: the timeline stays one screen of events
TOP_UNCLASSIFIED = 5    # untuned first value: enough unknown rules to grow HEAL_RULES/BUY_RULES
UNCLASSIFIED_MAX_SHARE = 0.05   # a rule this common is part of normal play, not an unknown to name
HEAL_BUY_ADJACENT = ("item", "potion", "mart", "center", "buy", "heal")  # names worth classifying


def _goal_firsts(data: RunData) -> list[str]:
    """Goals this run reached: goal_frames.jsonl first, else milestones.json entries for this run."""
    if data.goal_frames:
        return [r.get("goal") for r in data.goal_frames]
    return [g for g, es in data.milestones.items() if any(e.get("run") == data.name for e in es)]


def _header(data: RunData) -> dict:
    meta = data.meta
    by_source = Counter(str(t.get("source", "agent")) for t in data.transitions)
    frames = None
    for rows in (data.goal_frames, data.levels):
        f = rows[-1].get("frame") if rows else None
        if isinstance(f, (int, float)):
            frames = f if frames is None else max(frames, f)
    return {"segment": {"tag": meta.get("tag"), "stop_at_goal": meta.get("stop_at_goal"),
                        "stop_at_map": meta.get("stop_at_map")},
            "start": meta.get("start"), "starter": meta.get("starter"), "seed": meta.get("seed"),
            "git_sha": meta.get("git_sha"), "steps": len(data.decisions), "budget": meta.get("steps"),
            "presses_by_source": dict(by_source), "frames": frames}


def _end_reason(data: RunData, firsts: list[str]) -> dict:
    """Inferred end reason (there is no end-of-run marker file today). First match wins in the
    spec order solved > stalled > step_budget > crashed; the rest are reported under ``also``."""
    meta = data.meta
    checks = []
    if meta.get("stop_at_goal") and meta["stop_at_goal"] in firsts:
        checks.append("solved")
    if data.dossier:
        checks.append("stalled")
    if meta.get("steps") and len(data.decisions) >= meta["steps"]:
        checks.append("step_budget")
    if data.crashed:
        checks.append("crashed")
    last = (data.decisions or data.transitions or [{}])[-1]
    return {"inferred": True, "reason": checks[0] if checks else "ended_early", "also": checks[1:],
            "last_step": last.get("step"), "position": [last.get("map"), last.get("x"), last.get("y")]}


def _levels(data: RunData) -> dict:
    rows = data.levels
    if not rows:
        return {"first": None, "last": None, "gains": []}
    first, last = rows[0].get("party") or [], rows[-1].get("party") or []
    exp: dict[int, int] = {}
    prev = None
    for row in rows:
        party = row.get("party") or []
        if prev is not None:
            for i in range(min(len(prev), len(party))):
                if len(prev[i]) > 2 and len(party[i]) > 2 and party[i][2] > prev[i][2]:
                    exp[i] = exp.get(i, 0) + (party[i][2] - prev[i][2])
        prev = party
    return {"first": first, "last": last,
            "gains": [{"species": m[0], "level_from": first[i][1] if i < len(first) else None,
                       "level_to": m[1], "exp_gained": exp.get(i, 0)} for i, m in enumerate(last)]}


def _unclassified(decisions: list[dict], n: int = TOP_UNCLASSIFIED) -> list[dict]:
    """Rules matching NEITHER named tuple whose name is heal/buy-adjacent and that are rare enough
    (at most ``UNCLASSIFIED_MAX_SHARE`` of presses) to be a gap rather than the main behaviour."""
    out = []
    for r in top_rules(decisions, n=len(decisions) or 1):
        name = str(r["rule"]).lower()
        if any(t in name for t in HEAL_RULES) or any(t in name for t in BUY_RULES):
            continue
        if r["share"] > UNCLASSIFIED_MAX_SHARE or not any(t in name for t in HEAL_BUY_ADJACENT):
            continue
        out.append(r)
        if len(out) == n:
            break
    return out


def truncate_events(events: list[dict], max_events: int) -> tuple[list[dict], int]:
    """Cap the timeline at ``max_events`` without ever dropping a reserved event (stall, blackout,
    break-length loop). Returns (kept events in step order, number omitted)."""
    if len(events) <= max_events:
        return events, 0
    reserved = [e for e in events if is_reserved(e)]
    rest = [e for e in events if not is_reserved(e)]
    kept = reserved[:max_events] + rest[:max(0, max_events - len(reserved))]
    kept.sort(key=lambda e: (e.get("step") is None, e.get("step") or -1, e["kind"]))
    return kept, len(events) - len(kept)


def _breaks(data: RunData, episodes: list[dict]) -> list[dict]:
    """What makes the run a break (exit 1): a crash seam file, a long already_out/blocked loop,
    or a blackout. A stall alone is a result, not a break."""
    out = []
    if data.crashed:
        out.append({"kind": "crashed"})
    for e in episodes:
        if e["kind"] in ("already_out", "blocked_loop") and e["presses"] >= BREAK_LOOP_ROWS:
            out.append({"kind": e["kind"], "step": e["step"], "presses": e["presses"]})
    out += [{"kind": "blackout", "step": b.get("start"), "end_map": b.get("end_map")}
            for b in data.battles if b.get("outcome") == "blackout"]
    return out


def summarise(data: RunData, max_events: int = MAX_EVENTS) -> dict:
    """The whole run summary. ``event_counts`` is pre-collapse so diffs see real battle counts."""
    episodes = find_loops(data.transitions, data.decisions)
    events = build_events(data, episodes)
    event_counts = dict(Counter(e["kind"] for e in events))
    omitted = 0
    if len(events) > max_events:
        wild = [e for e in events if e["kind"] == "battle" and e.get("battle_kind") == 1]
        if wild:  # wild fights collapse into one wild_battles line when --max-events is tight
            keep = [e for e in events if e not in wild]
            keep.append({"kind": "wild_battles", "step": wild[0].get("step"), "count": len(wild),
                         "wins": sum(1 for e in wild if e.get("won"))})
            events = sorted(keep, key=lambda e: (e.get("step") is None, e.get("step") or -1, e["kind"]))
        events, omitted = truncate_events(events, max_events)
    return {"run": data.name,
            "start_time": data.start_time.isoformat(timespec="seconds") if data.start_time else None,
            "skipped_rows": data.skipped_rows,
            "header": _header(data),
            "events": events,
            "events_omitted": omitted,
            "event_counts": event_counts,
            "loops": collapse_loops(episodes),
            "long_loops": sum(1 for e in episodes if e["presses"] >= LONG_LOOP_ROWS),
            "rules": top_rules(data.decisions),
            "unclassified_rules": _unclassified(data.decisions),
            "levels": _levels(data),
            "end": _end_reason(data, _goal_firsts(data)),
            "breaks": _breaks(data, episodes)}
