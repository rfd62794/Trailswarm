"""The compressed event timeline: ``build_events(RunData) -> [Event]``, ordered by step.

Event ``kind`` values: goal, map, map_bounce, battle, wild_battles (a collapse added by
``timeline.summarise`` when --max-events is tight), blackout, heal, buy, stall, loop,
level, after_victory. Each carries ``step`` (None last) plus the fields its kind needs.
"""
from __future__ import annotations

from collections import Counter

from pokeagent.review.load import RunData
from pokeagent.review.loops import find_loops

HEAL_RULES = ("heal", "potion", "nurse", "cave_topup")   # named heal-class rule/behaviour substrings
BUY_RULES = ("restock", "buy", "shop")                  # named buy-class rule/behaviour substrings


def _map_of(pos) -> int | None:
    return (pos or [None])[0]


def _press_class(d: dict) -> str | None:
    """heal | buy | None for one decision row (behaviour or rule, substring match; heal wins ties)."""
    name = f"{d.get('behaviour')}|{d.get('rule')}".lower()
    if any(t in name for t in HEAL_RULES):
        return "heal"
    if any(t in name for t in BUY_RULES):
        return "buy"
    return None


def _goal_events(data: RunData) -> list[dict]:
    if data.goal_frames:
        return [{"kind": "goal", "goal": r.get("goal"), "step": r.get("step"),
                 "frame": r.get("frame")} for r in data.goal_frames]
    out = []
    for goal, entries in data.milestones.items():
        for e in entries:
            if e.get("run") == data.name:
                out.append({"kind": "goal", "goal": goal, "step": e.get("step"), "frame": None})
    return out


def _map_events(transitions: list[dict]) -> list[dict]:
    """Warp/map-change rows; an immediate A->B->A pair (or run of pairs) is one map_bounce event."""
    changes = [t for t in transitions if _map_of(t.get("to")) != _map_of(t.get("from"))]
    out, i, n = [], 0, len(changes)
    while i < n:
        a = _map_of(changes[i].get("from"))
        b = _map_of(changes[i].get("to"))
        count = 0
        while i + 2 * count + 1 < n:  # merge consecutive A->B->A cycles into one event with a count
            c1, c2 = changes[i + 2 * count], changes[i + 2 * count + 1]
            if (_map_of(c1.get("from")), _map_of(c1.get("to"))) != (a, b) or \
               (_map_of(c2.get("from")), _map_of(c2.get("to"))) != (b, a):
                break
            count += 1
        if count:
            last = changes[i + 2 * count - 1]
            out.append({"kind": "map_bounce", "step": changes[i].get("step"), "map_a": a, "map_b": b,
                        "count": count, "presses": (last.get("step") or 0) - (changes[i].get("step") or 0) + 1})
            i += 2 * count
        else:
            out.append({"kind": "map", "step": changes[i].get("step"), "from": a, "to": b})
            i += 1
    return out


def _hp(party: list | None) -> int:
    return sum(int(m[3]) for m in (party or []) if isinstance(m, (list, tuple)) and len(m) > 3
               and isinstance(m[3], (int, float)))


def _battle_events(battles: list[dict]) -> list[dict]:
    out = []
    for b in battles:
        base = {"step": b.get("start"), "battle_kind": b.get("kind"),
                "enemy_species": b.get("enemy_species"), "turns": len(b.get("turns") or []),
                "hp_delta": _hp(b.get("party_before")) - _hp(b.get("party_after")),  # positive = HP lost
                "end_map": b.get("end_map"), "won": bool(b.get("won"))}
        if b.get("outcome") == "blackout":
            out.append({"kind": "blackout", **base})
        else:
            out.append({"kind": "battle", "outcome": b.get("outcome"), **base})
    return out


def _block_events(decisions: list[dict]) -> list[dict]:
    """Contiguous heal/buy decision blocks: the first press of each block is one event with its count."""
    out, i, n = [], 0, len(decisions)
    while i < n:
        cls = _press_class(decisions[i])
        if cls is None:
            i += 1
            continue
        j = i + 1
        while j < n and _press_class(decisions[j]) == cls:
            j += 1
        rows = decisions[i:j]
        rule = Counter(str(r.get("rule")) for r in rows).most_common(1)[0][0]
        out.append({"kind": cls, "step": rows[0].get("step"), "presses": j - i, "rule": rule})
        i = j
    return out


def _stall_event(data: RunData) -> list[dict]:
    d = data.dossier
    if not d:
        return []
    return [{"kind": "stall", "step": d.get("presses"), "reason": d.get("reason"),
             "signature_key": d.get("signature_key"), "likely_cause": d.get("likely_cause"),
             "presses": d.get("presses"), "map": d.get("map"), "x": d.get("x"), "y": d.get("y")}]


def _level_events(levels: list[dict]) -> list[dict]:
    """Each levels.jsonl row after the first where any member's level or exp rose (index-aligned)."""
    out, prev = [], None
    for row in levels:
        party = row.get("party") or []
        if prev is not None:
            changes = []
            for i in range(min(len(prev), len(party))):
                a, b = prev[i], party[i]
                if len(a) > 2 and len(b) > 2 and (b[1] > a[1] or b[2] > a[2]):
                    changes.append({"species": b[0], "level_from": a[1], "level_to": b[1],
                                    "exp_gain": b[2] - a[2]})
            if changes:
                out.append({"kind": "level", "step": row.get("step"),
                            "frame": row.get("frame"), "changes": changes})
        prev = party
    return out


def build_events(data: RunData, episodes: list[dict] | None = None) -> list[dict]:
    """All timeline events for one run, ordered by step (kind second for stable order)."""
    eps = episodes if episodes is not None else find_loops(data.transitions, data.decisions)
    events = (
        _goal_events(data)
        + _map_events(data.transitions)
        + _battle_events(data.battles)
        + _block_events(data.decisions)
        + _stall_event(data)
        + [{"kind": "loop", "loop_kind": e["kind"], "step": e["step"], "presses": e["presses"],
            "key": e["key"], "rule": e["rule"]} for e in eps]
        + _level_events(data.levels)
        + [{"kind": "after_victory", **r} for r in data.after_victory]
    )
    return sorted(events, key=lambda e: (e.get("step") is None, e.get("step") or -1, e["kind"]))
