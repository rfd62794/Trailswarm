"""Build the novelty count table from runs that already exist. Read-only on runs/; the caller decides whether to write.

Per run, the features it touched (tiles, maps, map transitions from transitions.jsonl; maps and items of reached
milestones; enemy and party species and learned moves from battles.jsonl). A feature's count is the number of runs
that touched it, the same meaning the live deltas have.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.novelty.store import empty


def _lines(path: Path):
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def run_time(name: str) -> float:
    """Start time encoded in a run dir name (explore-YYYYmmdd-HHMMSS[-pid]); 0 when it is not one."""
    parts = name.split("-")
    try:
        return time.mktime(time.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S"))
    except (IndexError, ValueError, OverflowError):
        return 0.0


def transition_features(path: Path) -> set:
    out: set = set()
    for r in _lines(path):
        a, b = r.get("from"), r.get("to")
        if not (isinstance(a, list) and isinstance(b, list) and len(a) == 3 and len(b) == 3):
            continue
        for m, x, y in (a, b):
            out.add(f"t:{m}:{x}:{y}")
            out.add(f"m:{m}")
        if a[0] != b[0]:
            out.add(f"w:{a[0]}>{b[0]}")
    return out


def milestone_features(milestones: dict, campaign_goals: list) -> dict:
    """{run: {feature}}: a reached goal whose detector is a map or an item gives that map or item to the run."""
    det = {g["id"]: g.get("detector") if isinstance(g.get("detector"), dict) else {} for g in campaign_goals}
    out: dict = {}
    for goal, hits in milestones.items():
        d = det.get(goal) or {}
        keys = [f"m:{m}" for m in d.get("map", [])] if isinstance(d.get("map"), list) else []
        if isinstance(d.get("item"), int):
            keys.append(f"i:{d['item']}")
        for h in hits if isinstance(hits, list) else []:
            if isinstance(h, dict) and h.get("run") and not h.get("skipped"):
                out.setdefault(h["run"], set()).update(keys)
    return out


def battle_features(path: Path) -> dict:
    out: dict = {}
    for r in _lines(path):
        run = r.get("run")
        if not run:
            continue
        s = out.setdefault(run, set())
        if r.get("enemy_species"):
            s.add(f"ss:{r['enemy_species']}")
        for key in ("party_before", "party_after"):
            for row in r.get(key) or []:
                if row:
                    s.add(f"so:{row[0]}")
        for ml in r.get("moves_learned") or []:
            s.update(f"mv:{m}" for m in ml.get("moves", []))
    return out


def build_table(runs_dir: Path | str) -> dict:
    runs_dir = Path(runs_dir)
    per_run: dict = {}
    for d in sorted(runs_dir.glob("explore-*")):
        t = d / "transitions.jsonl"
        if t.is_file():
            per_run[d.name] = transition_features(t)
    goals = json.loads((Path(__file__).resolve().parent.parent / "data" / "campaign.json").read_text(encoding="utf-8"))["goals"]
    try:
        ms = json.loads((runs_dir / "milestones.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ms = {}
    extra = milestone_features(ms, goals)
    for run, feats in battle_features(runs_dir / "battles.jsonl").items():
        extra.setdefault(run, set()).update(feats)
    for run, feats in extra.items():
        per_run.setdefault(run, set()).update(feats)
    table = empty()
    counts, first = table["counts"], table["first"]
    for run, feats in per_run.items():
        ts = run_time(run)
        for k in feats:
            counts[k] = counts.get(k, 0) + 1
            if k not in first or ts < first[k][0]:
                first[k] = [ts, "backfill", run]
    table["merged"] = list(per_run)[-5000:]
    table["role_runs"] = {"backfill": len(per_run)}
    return table


def diff_tables(old: dict, new: dict) -> dict:
    """What a rebuild would change versus the table on disk (counts only)."""
    a, b = old.get("counts", {}), new.get("counts", {})
    return {"keys_old": len(a), "keys_new": len(b), "added": sum(k not in a for k in b), "dropped": sum(k not in b for k in a),
            "changed": sum(k in a and a[k] != b[k] for k in b)}
