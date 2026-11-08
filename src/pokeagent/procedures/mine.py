"""Learning a procedure from the best organic run (the segmentation rule of tools/review_runs.py, factored
into a small function so the tool stays a script): fewest presses between the previous goal's first step and
this goal's first step, then compress to waypoints / interactions / trainer fights."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.explorer.world import DIRS
from pokeagent.goals import GOALS
from pokeagent.procedures.schema import FIGHT_MAX_FRAMES, FIGHT_MAX_PRESSES, GOTO_MAX_FRAMES, GOTO_MAX_PRESSES

MIN_SEGMENT = 4      # a shorter segment is noise, not a script (untuned first value)
MAX_SEGMENT = 1500   # a longer segment is a wander, not a route (untuned first value)
WAYPOINT_EVERY = 12  # a straight run of moves compresses to a waypoint every N moved rows (untuned first value)
TURN_MIN = 2         # a waypoint also at a turn with more than this many direction changes in 4 rows (untuned)
REGION_PAD = 2       # a step's precondition carries a region this many tiles around the previous waypoint (untuned)


def load_runs(root: Path):
    for d in sorted(root.glob("explore-*")):
        f = d / "transitions.jsonl"
        if f.exists():
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            if rows:
                yield d.name, rows


def goal_steps_for(run: str, milestones: dict) -> dict:
    return {g: min(e["step"] for e in v if e["run"] == run) for g, v in milestones.items() if any(e["run"] == run for e in v)}


def best_segment(goal: str, runs: dict, milestones: dict):
    """(run_name, segment_rows) of the run with the fewest presses into ``goal`` (review_runs' rule), or None."""
    best = None
    for run, rows in runs.items():
        gs = goal_steps_for(run, milestones)
        prev = 0
        for g in GOALS:
            if g in gs:
                if g == goal:
                    seg = [r for r in rows if prev < r["step"] <= gs[g]]
                    length = gs[g] - prev
                    if length > 0 and (best is None or length < best[0]):
                        best = (length, run, seg)
                    break
                prev = max(prev, gs[g])
    return None if best is None else (best[1], best[2])


def _region(frm) -> dict:
    m, x, y = frm
    return {"region": [m, x - REGION_PAD, y - REGION_PAD, x + REGION_PAD, y + REGION_PAD]}


def steps_from_segment(seg: list, battles: list) -> list:
    """Compress a winning segment into steps: goto per warp, interact per none->dialog flip, fight per trainer
    battle, and a waypoint every WAYPOINT_EVERY moved rows or every turn of >TURN_MIN changes in 4 rows."""
    marks = []   # (row_index, order, step dict)
    moves, dirs = 0, []
    prev_frm = seg[0]["from"] if seg else None
    seq = 0
    for i, r in enumerate(seg):
        frm, to = r["from"], r["to"]
        pre = {"all": [{"map": frm[0]}, _region(prev_frm)]} if prev_frm else {"all": [{"map": frm[0]}]}
        if to[0] != frm[0]:  # a warp: a goto to the arrival tile
            marks.append((i, seq, {"kind": "goto", "to": to, "pre": pre})); seq += 1
            moves, dirs, prev_frm = 0, [], frm
            continue
        nxt = seg[i + 1] if i + 1 < len(seg) else None
        if r.get("textbox") == "none" and nxt is not None and nxt.get("textbox") == "dialog":
            marks.append((i, seq, {"kind": "interact", "at": frm, "face": r.get("facing", "UP"), "pre": pre})); seq += 1
            moves, dirs, prev_frm = 0, [], frm
            continue
        if r.get("button") in DIRS and r.get("moved"):
            moves += 1
            dirs = (dirs + [r["button"]])[-4:]
            turns = sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)
            if moves >= WAYPOINT_EVERY or (len(dirs) >= 4 and turns > TURN_MIN):
                marks.append((i, seq, {"kind": "goto", "to": to, "pre": pre})); seq += 1
                moves, dirs, prev_frm = 0, [], frm
    for b in battles:  # trainer fights whose start step falls inside the segment (wild fights are noise)
        t = b.get("trainer") or {}
        at = [t.get("map"), t.get("x"), t.get("y")] if "x" in t and "y" in t else None
        if at is None or at[0] is None:
            continue
        idx = next((j for j, r in enumerate(seg) if r["step"] >= b["start"]), len(seg))
        pre = {"all": [{"map": at[0]}, {"not": {"trainer_beaten": at}}]}
        marks.append((idx, seq, {"kind": "fight", "at": at, "pre": pre})); seq += 1
    marks.sort(key=lambda m: (m[0], m[1]))
    out = []
    for _, _, m in marks:
        sid = f"s{len(out) + 1}"
        if m["kind"] == "goto":
            out.append({"id": sid, "optional": False, "pre": m["pre"],
                        "action": {"kind": "goto", "map": m["to"][0], "x": m["to"][1], "y": m["to"][2]},
                        "effect": {"all": [{"at": m["to"]}]},
                        "ok": 0, "fail": 0, "max_presses": GOTO_MAX_PRESSES, "max_frames": GOTO_MAX_FRAMES})
        elif m["kind"] == "interact":
            at = m["at"]
            out.append({"id": sid, "optional": False, "pre": m["pre"],
                        "action": {"kind": "interact", "map": at[0], "x": at[1], "y": at[2], "face": m["face"]},
                        "effect": {"all": [{"at": at}]},
                        "ok": 0, "fail": 0, "max_presses": GOTO_MAX_PRESSES, "max_frames": GOTO_MAX_FRAMES})
        else:
            at = m["at"]
            out.append({"id": sid, "optional": False, "pre": m["pre"],
                        "action": {"kind": "behaviour", "name": "fight_trainer", "at": at},
                        "effect": {"all": [{"trainer_beaten": at}]},
                        "ok": 0, "fail": 0, "max_presses": FIGHT_MAX_PRESSES, "max_frames": FIGHT_MAX_FRAMES})
    return out


def build_procedure(goal: str, seg: list, battles: list) -> dict:
    return {"version": 1, "goal": goal, "source": "mined",
            "attempts": 0, "successes": 0, "best_frames": None, "best_presses": None,
            "disabled": False, "fail_streak": 0, "steps": steps_from_segment(seg, battles)}
