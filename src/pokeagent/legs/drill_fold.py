"""Fold drill results (runs/legs/drills.jsonl) into the per-leg records of runs/legs.json as samples marked source="drill".

A leg record keeps its natural samples apart (``frames_run``, ``samples_run``, ``efficiency_run``) so folding is repeatable:
``samples`` / ``best_frames`` / ``median_frames`` / ``efficiency`` always cover natural + drill samples. A drill matches a leg
on (map, entry, exit); when the drill knows the leaving button it must match too.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from pokeagent.legs.split import drill_leg

KEEP_SUMMARIES = 10
AT_PAR = 0.9   # a solved drill at >= 90% efficiency "hit par"


def load_drills(path: str | Path) -> list[dict]:
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("kind") == "leg" and "model_frames" in d and "par_frames" in d:
                out.append(d)
    except OSError:
        pass
    return out


def matches(rec: dict, d: dict) -> bool:
    return (rec["map"] == d["map"] and list(rec["entry"]) == list(d["entry"]) and list(rec["exit"]) == list(d["exit"])
            and (not d.get("button") or d["button"] == rec.get("button")))


def natural_frames(rec: dict) -> list[float]:
    """The natural samples' frames; a record from before drills existed has only best/median, so rebuild a stand-in."""
    if "frames_run" in rec:
        return list(rec["frames_run"])
    n = int(rec.get("samples_run", rec.get("samples", 0)))
    return ([rec["best_frames"]] + [rec["median_frames"]] * (n - 1)) if n else []


def merge_drills(rec: dict, drills: list[dict]) -> dict:
    """``rec`` with the matching drills folded in (a new dict; ``rec`` untouched)."""
    mine = [d for d in drills if matches(rec, d)]
    run = natural_frames(rec)
    out = dict(rec, frames_run=run, samples_run=len(run))
    out["efficiency_run"] = (rec["par_frames"] / min(run)) if run and min(run) > 0 and rec.get("par_frames") is not None else None
    legs = [drill_leg(d) for d in mine]
    allf = run + [l.frames for l in legs]
    out["drill_n"], out["drill_solved"] = len(mine), sum(bool(d.get("solved")) for d in mine)
    out["drills"] = [{"source": "drill", "run": d.get("run"), "t": d.get("t"), "solved": bool(d.get("solved")), "reason": d.get("reason"),
                      "model_frames": d["model_frames"], "efficiency": d.get("efficiency")} for d in mine[-KEEP_SUMMARIES:]]
    if mine and allf and rec.get("par_frames") is not None:
        pool = run + [l.frames for l in legs if l.complete]
        best = min(pool) if pool else rec["best_frames"]   # a failed drill is a sample (it costs >= 3 x par) but never the best
        out.update(samples=len(allf), best_frames=best, median_frames=statistics.median(allf),
                   efficiency=rec["par_frames"] / best if best > 0 else None)
    return out


def hit_par(d: dict) -> bool:
    return bool(d.get("solved")) and d.get("efficiency") is not None and d["efficiency"] >= AT_PAR


def fold_file(legs_path: str | Path, drills_path: str | Path) -> int:
    """In place: re-fold every drill into runs/legs.json. Returns the number of leg records that have drills. No-op without both."""
    p = Path(legs_path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    drills = load_drills(drills_path)
    n = 0
    for k, rec in list(doc.get("legs", {}).items()):
        new = merge_drills(rec, drills)
        n += bool(new["drill_n"])
        doc["legs"][k] = new
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(p)
    return n
