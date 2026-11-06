"""Build the RL/imitation dataset from runs/explore-*/transitions.jsonl.

    uv run python tools/rl_dataset.py [--runs runs] [--out runs/rl_dataset]

Claude's spec: dedupe identical rows, keep only segments that ended in the goal
(per runs/milestones.json), split by goal + checkpoint (a run is all-in or
all-out, never split by row), and count stall windows (long repeats of the
same from+button, the loop signature from the overnight log).

Writes <out>/summary.json and <out>/<goal>.jsonl shards (one row per transition,
with run/start/starter attached). Prints the same stats.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from pokeagent.goals import GOALS  # single source of the goal ladder

STALL_LEN = 8  # consecutive identical (from, button) rows that mark a loop


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="runs/rl_dataset")
    ap.add_argument("--drop-stalls", action="store_true",
                    help="omit rows inside stall windows from the shards (they are always counted)")
    a = ap.parse_args()

    runs_dir = Path(a.runs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    ms = load_json(runs_dir / "milestones.json", {})
    reached: dict[str, set[str]] = {g: {e["run"] for e in v} for g, v in ms.items()}

    dirs = sorted(p for p in runs_dir.glob("explore-*") if (p / "transitions.jsonl").exists())
    stats = defaultdict(Counter)
    global_hashes: set[str] = set()
    total_rows = 0
    sources = Counter()
    kept_runs = 0

    shards = {g: (out / f"{g}.jsonl").open("w", encoding="utf-8") for g in GOALS}
    try:
        for d in dirs:
            meta = load_json(d / "meta.json", {})
            goal = meta.get("stop_at_goal")
            if goal not in GOALS or d.name not in reached.get(goal, set()):
                continue  # not a successful segment run
            kept_runs += 1
            run = d.name
            s = stats[goal]
            s["runs"] += 1
            prev_key = None
            stall_run = 0
            buf = []
            for line in (d / "transitions.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total_rows += 1
                sources[row.get("source", "<missing>")] += 1
                s["rows"] += 1
                key = (tuple(row.get("from") or ()), row.get("button"))
                stall_run = stall_run + 1 if key == prev_key else 1
                prev_key = key
                if stall_run == STALL_LEN:
                    s["stall_windows"] += 1
                if stall_run >= STALL_LEN:
                    s["stall_rows"] += 1
                    if a.drop_stalls:
                        continue
                h = hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()
                if h in global_hashes:
                    s["dup_rows"] += 1
                    continue
                global_hashes.add(h)
                s["unique_rows"] += 1
                row["_run"] = run
                row["_start"] = meta.get("start")
                row["_starter"] = meta.get("starter")
                row["_seed"] = meta.get("seed")
                buf.append(json.dumps(row, separators=(",", ":")))
            if buf:
                shards[goal].write("\n".join(buf) + "\n")
    finally:
        for f in shards.values():
            f.close()

    summary = {
        "total_transition_rows": total_rows,
        "successful_segment_runs": kept_runs,
        "unique_rows_globally": len(global_hashes),
        "sources": dict(sources),
        "stall_len": STALL_LEN,
        "drop_stalls": a.drop_stalls,
        "goals": {g: dict(stats[g]) for g in GOALS if stats[g]},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"\nshards + summary in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
