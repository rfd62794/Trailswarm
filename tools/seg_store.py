"""Segment curriculum store: runs/segments.json, the segment layout (with splits) and per-segment stats.

A segment is the stretch between two goals (GOALS[i-1] -> GOALS[i]) or, once split, between two map entries inside
it. Stats are over attempts (one headless segment run each); a segment counts as SOLVED at >= SOLVED_RATE over its
last WINDOW attempts. Expected frames include the cost of failures: a failed attempt costs the frames it burned
(steps x frames-per-press) plus a penalty proportional to what a solve costs (half the segment's median solve, at
least PENALTY_FLOOR), so a fast-but-flaky route does not beat a steady one. Frames per press is CALIBRATED from the
runs' own goal_frames.jsonl (doc["calib"]); until enough data exists it is FRAMES_PER_STEP.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from functools import lru_cache

from pokeagent import checkpoint_goals as cg
from pokeagent.campaign import agent_capabilities, selectable
from pokeagent.goals import GOALS
from pokeagent.segment_names import BEST_SUFFIX

WINDOW = 20
SOLVED_RATE = 0.9
PENALTY_FRAC = 0.5           # a failure also costs this share of the segment's typical solve
PENALTY_FLOOR = 600          # ...but at least 10 s of game time
FRAMES_PER_STEP = 10.5       # measured 2026-11-05: 1,115,594 frames / 105,981 presses over real goal_frames deltas
CALIB_MIN_STEPS = 2000       # presses of evidence before the measured ratio replaces FRAMES_PER_STEP
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
    return {"version": 1, "ingested": [], "splits": {}, "stats": {}, "calib": {"frames": 0, "steps": 0}}


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


@lru_cache(maxsize=8)
def _selectable(caps: frozenset) -> tuple[str, ...]:
    return tuple(g for g in GOALS if selectable(g, caps))


def selectable_goals() -> tuple[str, ...]:
    """The goals a segment may target (campaign.selectable): reachable through the chain AND with a verified detector.
    Surf/Cut-gated goals and everything after them, and unverified goals, are never scheduled or split."""
    return _selectable(frozenset(agent_capabilities()))


LOCK_WAIT_S = 10.0
LOCK_STALE_S = 60.0


@contextlib.contextmanager
def locked(root: Path):
    """Read-modify-write of runs/segments.json under a short lock: yields the doc as it is ON DISK right now and saves it
    on a clean exit, so two supervisors (a rolling upgrade, a second swarm) can never overwrite each other's ingest."""
    lock = root / "runs" / "segments.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()  # a crashed writer's leftover
                    continue
            if time.monotonic() > end:
                raise TimeoutError(f"{lock} is held; another supervisor is writing the curriculum")
            time.sleep(0.05)
    try:
        doc = load(root)
        yield doc
        save(root, doc)
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def remove_tree(root: Path, path: Path, log=print) -> bool:
    """Delete a kept dir, but only inside runs/segments (never anything else); failures are logged, not swallowed."""
    base = (root / "runs" / "segments").resolve()
    target = Path(path).resolve()
    if base not in target.parents:
        log(f"curriculum: refusing to delete {path}: outside {base}")
        return False
    if not target.exists():
        return True
    errors: list[str] = []
    shutil.rmtree(target, onexc=lambda f, p, e: errors.append(f"{p}: {e!r}"))
    if errors:
        log(f"curriculum: could not fully delete {target}: {errors[0]}")
    return not target.exists()


def layout(doc: dict) -> list[Segment]:
    """Every leaf segment in chain order; a split goal is replaced by its sub-segments. Only selectable goals get a
    segment; an unverified goal in between is covered by the next one (it starts from the last selectable checkpoint)."""
    out: list[Segment] = []
    prev_goal = "bedroom"
    for g in selectable_goals():
        start, prev_goal = prev_goal, g
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


def fps(doc: dict) -> float:
    """Frames per press: measured from this install's goal_frames deltas once there are enough, else the default."""
    c = doc.get("calib") or {}
    return c["frames"] / c["steps"] if c.get("steps", 0) >= CALIB_MIN_STEPS else FRAMES_PER_STEP


def fail_penalty(st: dict) -> float:
    solved = sorted(a["frames"] for a in window(st) if a["solved"])
    return max(PENALTY_FLOOR, PENALTY_FRAC * solved[len(solved) // 2]) if solved else PENALTY_FLOOR


def attempt_cost(a: dict, per_step: float, penalty: float) -> float:
    return a["frames"] if a["solved"] else a["steps"] * per_step + penalty


def expected_frames(st: dict, per_step: float = FRAMES_PER_STEP) -> float | None:
    """Mean frames to ONE solve over the window: all attempts' cost (failures included) / solves. None = no solve."""
    w = window(st)
    solves = sum(1 for a in w if a["solved"])
    pen = fail_penalty(st)
    return sum(attempt_cost(a, per_step, pen) for a in w) / solves if solves else None


def potential_gain(st: dict, per_step: float = FRAMES_PER_STEP) -> float:
    """What polishing could still win: expected frames minus the best known solve (0 when either is unknown)."""
    e, b = expected_frames(st, per_step), best_frames(st)
    return max(0.0, e - b) if e is not None and b is not None else 0.0


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


def ckpt_valid(root: Path, name: str) -> bool:
    """May checkpoint ``name`` start a segment? Only if every earlier selectable goal was complete when it was written
    (sidecar), or - for an old checkpoint with no sidecar - has a checkpoint of its own (no gap in the chain)."""
    if name == "bedroom":
        return ckpt(root, name) is not None
    return cg.valid(name, ckpt(root, name), selectable_goals(), lambda g: ckpt(root, g) is not None)


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


def job_dir(root: Path, tag: str) -> Path:
    """Everything a job must keep so its solve can be replayed: starting map memory + the exact start state file."""
    return root / "runs" / "segments" / "inputs" / re.sub(r"[^A-Za-z0-9_.@-]", "_", tag)


def input_path(root: Path, tag: str) -> Path:
    return job_dir(root, tag) / "maps.json"


REPLAY_KEYS = ("seed", "starter", "explore_rate", "box_pace")   # what a faithful replay must know


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replayable(b: dict | None) -> bool:
    """A best can be confirmed only if its seed/pace settings, starting map memory AND exact start state (path + sha256,
    both kept under runs/segments/inputs/) are all still there and unchanged."""
    if not b or not b.get("input") or not b.get("start") or not Path(b["input"]).exists() or not Path(b["start"]).exists():
        return False
    return all(b.get(k) is not None for k in REPLAY_KEYS) and sha256(b["start"]) == b.get("start_sha")
