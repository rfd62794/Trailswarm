"""Stuck signals: pure checks over a snapshot dict (and its ``extra``) that say WHY an agent looks stuck.

Each signal is ``{"kind", "reason"}``. They read the compact recent-decision list the agent publishes in
``extra["decisions"]`` (newest last; keys s step, r rule, b button, m/x/y position, o outcome, bx box, bt battle, d driver)
and ``extra["box_hist"]`` (the text-box text at each recent snapshot).
"""
from __future__ import annotations

import re

RULE_REPEAT_N = 12   # same rule this many decisions in a row with no progress
NO_TILE_M = 24       # this many overworld decisions on <= 2 distinct tiles
BOX_REPEAT_N = 4     # the same box text in this many of the last snapshots
PROGRESS = ("moved", "map_change", "goal")
NO_EFFECT = re.compile(r"have any\s*effect", re.IGNORECASE)  # "It won't have any effect." (the apostrophe glyph is lost)


def _agent_decisions(extra: dict) -> list[dict]:
    return [d for d in extra.get("decisions", []) if d.get("d", "agent") != "claude"]


def rule_repeat(decs: list[dict], n: int = RULE_REPEAT_N) -> dict | None:
    tail = decs[-n:]
    if len(tail) < n or len({d.get("r") for d in tail}) != 1 or any(d.get("o") in PROGRESS for d in tail):
        return None
    return {"kind": "rule_repeat", "reason": f"rule '{tail[-1].get('r')}' repeated {n}x with no progress"}


def no_new_tile(decs: list[dict], m: int = NO_TILE_M) -> dict | None:
    walk = [d for d in decs if not d.get("bx") and not d.get("bt")]
    tail = walk[-m:]
    if len(tail) < m or len({(d.get("m"), d.get("x"), d.get("y")) for d in tail}) > 2:
        return None
    return {"kind": "no_new_tile", "reason": f"no new tile in {m} overworld steps (around {tail[-1].get('x')},{tail[-1].get('y')})"}


def item_loop(snap: dict) -> dict | None:
    extra = snap.get("extra") or {}
    texts = [snap.get("screen", {}).get("box_text", ""), " ".join(snap.get("sees", {}).get("rows", []))]
    hist = [t for t in extra.get("box_hist", []) if NO_EFFECT.search(t)]
    if any(NO_EFFECT.search(t) for t in texts) or len(hist) >= 2:
        return {"kind": "item_loop", "reason": "item 'won't have any effect' text on screen (using an item that cannot help)"}
    return None


def box_repeat(extra: dict, n: int = BOX_REPEAT_N) -> dict | None:
    hist = [t for t in extra.get("box_hist", [])[-6:] if t]
    top = max(set(hist), key=hist.count) if hist else ""
    if top and hist.count(top) >= n:
        return {"kind": "box_repeat", "reason": f"same box text {hist.count(top)}x: \"{top[:60]}\""}
    return None


def stall_guard(decs: list[dict]) -> dict | None:
    if any(d.get("r") == "stall_escalate" for d in decs[-10:]):
        return {"kind": "stall_guard", "reason": "the stall guard fired (escalating presses) in the last 10 decisions"}
    return None


def stuck_signals(snap: dict) -> list[dict]:
    """All signals that currently hold. A paused or human-steered agent is still on purpose, so only the item loop counts."""
    extra = snap.get("extra") or {}
    decs = _agent_decisions(extra)
    out = [item_loop(snap)]
    if snap.get("state") != "paused" and not snap.get("human_hold"):
        out += [rule_repeat(decs), no_new_tile(decs), box_repeat(extra), stall_guard(decs)]
    return [s for s in out if s]
