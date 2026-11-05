"""Auto-define sub-goal milestones from a successful run's path (exploration lane).

    uv run python tools/rl_curriculum.py --segment reach_pc --from-run runs/explore-XXXX --waypoints 4

Reads the run's transitions.jsonl, takes the first-visit positions along the
path, samples --waypoints evenly spaced milestones, and writes them into
runs/rl_curriculum.json under the segment name. rl_env turns each waypoint
into a shaped sub-goal automatically — the best known path teaches the next
learner where to go.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CURR = Path("runs/rl_curriculum.json")


def load() -> dict:
    return json.loads(CURR.read_text()) if CURR.exists() else {}


def save(data: dict) -> None:
    CURR.write_text(json.dumps(data, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", required=True)
    ap.add_argument("--from-run", required=True, help="run dir with transitions.jsonl of a successful pass")
    ap.add_argument("--waypoints", type=int, default=4)
    ap.add_argument("--label", default=None, help="human label for the mined steps (marks intent, still silver)")
    a = ap.parse_args()

    rows = [json.loads(ln) for ln in open(Path(a.from_run) / "transitions.jsonl")]
    seen, path = set(), []
    for r in rows:  # first-visit positions only: loops compress to the efficient path
        p = tuple(r["to"])
        if p not in seen:
            seen.add(p)
            path.append(p)
    if len(path) < 2:
        print("path too short to mine"); return 1
    wps = [path[int(i * (len(path) - 1) / a.waypoints)] for i in range(1, a.waypoints + 1)]
    data = load()
    data[a.segment] = [{"pos": list(w), "label": a.label or f"step_{i + 1}",
                        "quality": "silver"} for i, w in enumerate(wps)]  # silver until a human labels/golds it
    save(data)
    print(f"{a.segment}: {len(wps)} milestones mined from {len(path)} distinct positions -> {CURR}")
    for w in wps:
        print("  ", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
