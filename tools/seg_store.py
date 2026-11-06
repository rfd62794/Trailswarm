"""Segment curriculum store: runs/segments.json, the segment layout (with splits) and per-segment stats.

A segment is the stretch between two goals (GOALS[i-1] -> GOALS[i]) or, once split, between two map entries inside
it. Stats are over attempts (one headless segment run each); a segment counts as SOLVED at >= SOLVED_RATE over its
last WINDOW attempts. Expected frames include the cost of failures: a failed attempt costs the frames it burned
(steps x FRAMES_PER_STEP) plus FAIL_PENALTY_FRAMES, so a fast-but-flaky route does not beat a steady one.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from pokeagent.goals import GOALS
from pokeagent.segment_names import BEST_SUFFIX

WINDOW = 20
SOLVED_RATE = 0.9
FAIL_PENALTY_FRAMES = 3600   # one minute of game time charged per failed attempt
FRAMES_PER_STEP = 12         # failed attempts record steps, not frames; this converts (measured: ~10-19 per press)
KEEP_ATTEMPTS = 60


@dataclass(frozen=True)
class Segment:
    key: str                 # a goal id, or "<goal>@<map hex>" / "<goal>@end" for a sub-segment
    goal: str                # the goal this segment belongs to
    start: str               # checkpoint base name it starts from ("bedroom" = baselines/bedroom.state)
    end: str                 # checkpoint base name it writes
    stop_goal: str | None    # --stop-at-goal value
    stop_map: int | None     # --stop-at-map value


def empty_doc() -> dict:
    return {"version": 1, "ingested": [], "splits": {}, "stats": {}}


def load(root: Path) -> dict:
    try:
        d = json.loads((root / "runs" / "segments.json").read_text(encoding="utf-8"))
        return {**empty_doc(), **d}
    except (OSError, json.JSONDecodeError):
        return empty_doc()


def save(root: Path, doc: dict) -> None:
    p = root / "runs" / "segments.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def layout(doc: dict) -> list[Segment]:
    """Every leaf segment in chain order; a split goal is replaced by its sub-segments."""
    out: list[Segment] = []
    for i, g in enumerate(GOALS):
        start = GOALS[i - 1] if i else "bedroom"
        subs = doc["splits"].get(g)
        if not subs:
            out.append(Segment(g, g, start, g, g, None))
            continue
        prev = start
        pieces = [*subs, None]  # N cut maps make N+1 sub-segments; the last one ends at the goal itself
        for k, m in enumerate(pieces):
            last = m is None
            key = f"{g}@end" if last else f"{g}@{m:02x}"
            out.append(Segment(key, g, prev, g if last else key, g if last else None, None if last else m))
            prev = key
    return out


def stat(doc: dict, key: str) -> dict:
    return doc["stats"].setdefault(key, {"attempts": [], "n": 0, "solves": 0, "best": None, "confirmed": None})


def window(st: dict) -> list[dict]:
    return st["attempts"][-WINDOW:]


def rate(st: dict) -> float | None:
    w = window(st)
    return sum(1 for a in w if a["solved"]) / len(w) if w else None


def is_solved(st: dict) -> bool:
    r = rate(st)
    return r is not None and len(window(st)) >= WINDOW and r >= SOLVED_RATE


def attempt_cost(a: dict) -> int:
    return a["frames"] if a["solved"] else a["steps"] * FRAMES_PER_STEP + FAIL_PENALTY_FRAMES


def expected_frames(st: dict) -> float | None:
    """Mean frames to ONE solve over the window: all attempts' cost (failures included) / solves. None = no solve."""
    w = window(st)
    solves = sum(1 for a in w if a["solved"])
    return sum(attempt_cost(a) for a in w) / solves if solves else None


def accepted(st: dict) -> dict | None:
    """The route we stand behind: the fastest CONFIRMED solve, else the fastest seen (flagged unconfirmed), else the
    fastest solve of an old run whose frames were only estimated from its press count (``est``)."""
    if st["confirmed"] or st["best"]:
        return st["confirmed"] or st["best"]
    est = [a for a in st["attempts"] if a["solved"]]
    return {**min(est, key=lambda a: a["frames"]), "est": True} if est else None


def best_frames(st: dict) -> int | None:
    b = accepted(st)
    return b["frames"] if b else None


def ckpt(root: Path, name: str) -> Path | None:
    """Best existing checkpoint for a base name: <name>.best.state (confirmed) beats <name>.state; bedroom = baseline."""
    if name == "bedroom":
        p = root / "baselines" / "bedroom.state"
        return p if p.exists() else None
    d = root / "runs" / "checkpoints"
    return next((p for p in (d / f"{name}{BEST_SUFFIX}.state", d / f"{name}.state") if p.exists()), None)


def chain(doc: dict) -> dict:
    """The concatenated best route: per-segment accepted frames, total, how many are missing / unconfirmed."""
    rows, total, missing, unconfirmed = [], 0, [], []
    for s in layout(doc):
        st = stat(doc, s.key)
        f = best_frames(st)
        rows.append((s.key, f))
        if f is None:
            missing.append(s.key)
        else:
            total += f
            if st["confirmed"] is None:
                unconfirmed.append(s.key)
    return {"rows": rows, "total": total, "missing": missing, "unconfirmed": unconfirmed,
            "complete": not missing and bool(rows)}


def input_path(root: Path, tag: str) -> Path:
    """Where a job's starting map memory is kept until we know whether its solve needs a replay."""
    return root / "runs" / "segments" / "inputs" / (re.sub(r"[^A-Za-z0-9_.@-]", "_", tag) + ".json")


REPLAY_KEYS = ("seed", "starter", "explore_rate", "box_pace")   # what a faithful replay must know


def replayable(b: dict | None) -> bool:
    """A best can be confirmed only if its seed/pace settings AND starting map memory were kept."""
    return bool(b and b.get("input") and Path(b["input"]).exists() and all(b.get(k) is not None for k in REPLAY_KEYS))
