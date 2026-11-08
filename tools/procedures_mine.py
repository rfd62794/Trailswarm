"""Mine goal procedures from the best organic runs:

    uv run python tools/procedures_mine.py [--runs runs] [--out runs/procedures] [--goal GOAL ...] [--force]

For each goal, picks the best organic run exactly as review_runs.py does (fewest presses between the previous
goal's first step and this goal's first step, from runs/milestones.json and each run's transitions.jsonl),
skips segments under MIN_SEGMENT / over MAX_SEGMENT presses, and writes runs/procedures/<goal>.json with
source "mined" and zeroed counts. Re-mining never overwrites a procedure with attempts >= 3 and a better
success rate unless --force. A missing runs/ is a clean "nothing to mine" exit 0.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pokeagent.goals import GOALS
from pokeagent.procedures import mine
from pokeagent.procedures.schema import from_json


def _battles(root: Path) -> dict:
    """run name -> trainer-battle records (kind == 2, won, pinned to an NPC)."""
    out: dict = {}
    path = root / "battles.jsonl"
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if rec.get("kind") == 2 and rec.get("won") and rec.get("trainer"):
                out.setdefault(rec.get("run", ""), []).append(rec)
    return out


def _existing(path: Path):
    try:
        return from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="runs/procedures")
    ap.add_argument("--goal", nargs="*", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.runs)
    if not root.exists() or not (root / "milestones.json").exists():
        print("nothing to mine: no runs/ or no milestones.json")
        return 0
    ms = json.loads((root / "milestones.json").read_text(encoding="utf-8"))
    runs = dict(mine.load_runs(root))
    battles = _battles(root)
    out_dir = Path(args.out)
    made = 0
    for goal in (args.goal or GOALS):
        best = mine.best_segment(goal, runs, ms)
        if best is None:
            continue
        run, seg = best
        if not (mine.MIN_SEGMENT <= len(seg) <= mine.MAX_SEGMENT):
            print(f"  {goal}: segment of {len(seg)} presses skipped (bounds {mine.MIN_SEGMENT}-{mine.MAX_SEGMENT})")
            continue
        proc = mine.build_procedure(goal, seg, battles.get(run, []))
        out = out_dir / f"{goal}.json"
        if out.exists() and not args.force:
            cur = _existing(out)
            if cur is not None and cur.attempts >= 3 and cur.successes > 0:
                print(f"  {goal}: kept the existing graded procedure ({cur.successes}/{cur.attempts} won)")
                continue
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(proc, indent=1), encoding="utf-8")
        tmp.replace(out)
        made += 1
        print(f"  {goal}: {len(proc['steps'])} steps from {run} ({len(seg)} presses) -> {out}")
    print(f"{made} procedure(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
