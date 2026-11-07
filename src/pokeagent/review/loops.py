"""Loop detection: maximal runs of identical press keys in transitions.jsonl.

Two key shapes: the same ``(button, normalised screen text)`` for a press row with a text box up,
and the same ``(map, x, y, button)`` for a direction press where ``moved`` is false. A row matching
neither shape (a moved press with no text) breaks a run. An episode is a run of at least
``LOOP_MIN_ROWS`` consecutive rows sharing one key.
"""
from __future__ import annotations

from collections import Counter

LOOP_MIN_ROWS = 6    # untuned first value: a real loop; a 5-row repeat is still normal play
LOOP_TEXT_LEN = 60   # untuned first value: enough of the screen text to identify the loop
BREAK_LOOP_ROWS = 30  # untuned first value: an episode this long is a break, not a hiccup
LONG_LOOP_ROWS = 10   # untuned first value: an episode this long is reported as a long loop


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _key(row: dict):
    """The loop key of one transition row, or None when it can never belong to an episode."""
    text = _norm(row.get("text"))
    if text:
        return ("text", row.get("button"), text[:LOOP_TEXT_LEN])
    if row.get("moved") is False:
        to = row.get("to") or [None, None, None]
        return ("blocked", row.get("button"), to[0], to[1], to[2])
    return None


def find_loops(transitions: list[dict], decisions: list[dict] | None = None) -> list[dict]:
    """Loop episodes, oldest first. ``kind`` is ``already_out`` (screen text contains the phrase),
    ``blocked_loop`` (same tile/button, unmoved) or ``text_loop`` (same button + screen text)."""
    rules = {d.get("step"): d.get("rule") for d in (decisions or [])}
    episodes: list[dict] = []
    i, n = 0, len(transitions)
    while i < n:
        key = _key(transitions[i])
        if key is None:
            i += 1
            continue
        j = i + 1
        while j < n and _key(transitions[j]) == key:
            j += 1
        if j - i >= LOOP_MIN_ROWS:
            rows = transitions[i:j]
            if any("already out" in _norm(r.get("text")) for r in rows):
                kind = "already_out"
            elif key[0] == "blocked":
                kind = "blocked_loop"
            else:
                kind = "text_loop"
            dom = Counter(rules.get(r.get("step")) for r in rows if r.get("step") in rules)
            if key[0] == "text":
                shown = {"button": key[1], "text": key[2]}
            else:
                shown = {"button": key[1], "map": key[2], "x": key[3], "y": key[4]}
            episodes.append({"kind": kind, "step": rows[0].get("step"),
                             "end_step": rows[-1].get("step"), "presses": j - i,
                             "key": shown, "rule": dom.most_common(1)[0][0] if dom else None})
        i = j
    return episodes


def collapse_loops(episodes: list[dict]) -> list[dict]:
    """One entry per (kind, key) across the run, however many episodes repeat it.

    A near-threshold blocked tile can re-trigger the 6-row threshold dozens of times; that is one
    loop, not dozens. Each group: ``count`` episodes, ``total_presses``, ``max_presses``, the first
    ``step`` and last ``end_step``, the most common ``rule``, and ``long`` when any episode reached
    ``LONG_LOOP_ROWS``. Ordered by first step."""
    groups: dict[tuple, dict] = {}
    rules: dict[tuple, Counter] = {}
    for e in episodes:
        gk = (e["kind"], tuple(sorted(e["key"].items())))
        g = groups.get(gk)
        if g is None:
            g = groups[gk] = {"kind": e["kind"], "key": e["key"], "count": 0, "total_presses": 0,
                              "max_presses": 0, "step": e["step"], "end_step": e["end_step"],
                              "rule": None}
            rules[gk] = Counter()
        g["count"] += 1
        g["total_presses"] += e["presses"]
        g["max_presses"] = max(g["max_presses"], e["presses"])
        if e["step"] is not None and (g["step"] is None or e["step"] < g["step"]):
            g["step"] = e["step"]
        if e["end_step"] is not None and (g["end_step"] is None or e["end_step"] > g["end_step"]):
            g["end_step"] = e["end_step"]
        rules[gk][e["rule"]] += 1
    out = []
    for gk, g in groups.items():
        g["rule"] = rules[gk].most_common(1)[0][0]
        g["long"] = g["max_presses"] >= LONG_LOOP_ROWS
        out.append(g)
    return sorted(out, key=lambda g: (g["step"] is None, g["step"] or -1, g["kind"]))
