"""``pokeagent review diff``: both runs summarised with the run machinery, then compared."""
from __future__ import annotations

from pokeagent.review.load import RunData
from pokeagent.review.rules import top_rules
from pokeagent.review.timeline import summarise

RULE_SHARE_DELTA = 0.05   # untuned first value: a real shift in how the run spent its presses
COMPARE_META_KEYS = ("seed", "starter", "start", "git_sha", "steps")  # apples-to-apples check


def _pos(t: dict):
    to = t.get("to") or [None, None, None]
    return (t.get("button"), to[0], to[1], to[2])


def first_divergence(a: RunData, b: RunData) -> dict | None:
    """First step where (button, map, x, y) differs in the press streams (aligned on ``step``);
    rule/behaviour of each side joined from decisions.jsonl. None for identical or prefix streams."""
    ta = {t.get("step"): t for t in a.transitions}
    tb = {t.get("step"): t for t in b.transitions}
    da = {d.get("step"): d for d in a.decisions}
    db = {d.get("step"): d for d in b.decisions}
    for s in sorted(set(ta) & set(tb)):
        if _pos(ta[s]) != _pos(tb[s]):
            return {"step": s,
                    "a": {"button": ta[s].get("button"), "to": ta[s].get("to"),
                          "rule": da.get(s, {}).get("rule"), "behaviour": da.get(s, {}).get("behaviour")},
                    "b": {"button": tb[s].get("button"), "to": tb[s].get("to"),
                          "rule": db.get(s, {}).get("rule"), "behaviour": db.get(s, {}).get("behaviour")}}
    return None


def _goal_times(data: RunData) -> dict:
    if data.goal_frames:
        return {r["goal"]: {"step": r.get("step"), "frame": r.get("frame")} for r in data.goal_frames}
    out = {}
    for g, es in data.milestones.items():
        for e in es:
            if e.get("run") == data.name and g not in out:
                out[g] = {"step": e.get("step"), "frame": None}
    return out


def _goal_deltas(a: RunData, b: RunData) -> dict:
    ga, gb = _goal_times(a), _goal_times(b)
    out = {}
    for g in sorted(set(ga) | set(gb)):
        ta, tb = ga.get(g), gb.get(g)
        first = None
        if ta and tb and ta.get("step") is not None and tb.get("step") is not None:
            first = "a" if ta["step"] < tb["step"] else "b" if tb["step"] < ta["step"] else "tie"
        elif ta:
            first = "a"
        elif tb:
            first = "b"
        out[g] = {"a": ta, "b": tb,
                  "delta_steps": tb["step"] - ta["step"] if ta and tb and None not in
                                  (ta.get("step"), tb.get("step")) else None,
                  "delta_frames": tb["frame"] - ta["frame"] if ta and tb and None not in
                                  (ta.get("frame"), tb.get("frame")) else None,
                  "first": first}
    return out


def _segment_key(meta: dict) -> str | None:
    tag = str(meta.get("tag") or "")
    return tag.split(":")[1] if tag.startswith("seg:") else meta.get("stop_at_goal")


def _rule_shares(data: RunData) -> dict:
    return {r["rule"]: r["share"] for r in top_rules(data.decisions, n=len(data.decisions) or 1)}


def diff(a: RunData, b: RunData) -> dict:
    """The whole comparison; ``warnings`` come first - a diff still runs when runs are not comparable."""
    sa, sb = summarise(a), summarise(b)
    warnings = [{"field": k, "a": a.meta.get(k), "b": b.meta.get(k)}
                for k in COMPARE_META_KEYS if a.meta.get(k) != b.meta.get(k)]
    div = first_divergence(a, b)
    prefix = None
    if div is None and len(a.transitions) != len(b.transitions):
        prefix = min(len(a.transitions), len(b.transitions))
    seg_key = _segment_key(a.meta)
    seg_delta = None
    goals = _goal_deltas(a, b)
    if seg_key and seg_key == _segment_key(b.meta):
        stop = a.meta.get("stop_at_goal") or b.meta.get("stop_at_goal")
        if stop in goals:
            seg_delta = {"segment": seg_key, "delta_frames": goals[stop]["delta_frames"],
                         "delta_steps": goals[stop]["delta_steps"]}
    shares_a, shares_b = _rule_shares(a), _rule_shares(b)
    rule_deltas = [{"rule": r, "share_a": shares_a.get(r, 0.0), "share_b": shares_b.get(r, 0.0),
                    "delta": shares_b.get(r, 0.0) - shares_a.get(r, 0.0)}
                   for r in sorted(set(shares_a) | set(shares_b))
                   if abs(shares_b.get(r, 0.0) - shares_a.get(r, 0.0)) >= RULE_SHARE_DELTA]
    exp_a = sum(g["exp_gained"] for g in sa["levels"]["gains"])
    exp_b = sum(g["exp_gained"] for g in sb["levels"]["gains"])
    return {"a": a.name, "b": b.name,
            "warnings": warnings,
            "divergence": div,
            "prefix_only": prefix,
            "goals": goals,
            "segment": seg_delta,
            "event_counts": {k: {"a": sa["event_counts"].get(k, 0), "b": sb["event_counts"].get(k, 0)}
                             for k in sorted(set(sa["event_counts"]) | set(sb["event_counts"]))},
            "rule_deltas": rule_deltas,
            "exp": {"a": exp_a, "b": exp_b, "delta": exp_b - exp_a},
            "end": {"a": sa["end"], "b": sb["end"]}}
