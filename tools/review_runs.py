"""Review every explorer run: which presses, from where, led to which results - fastest vs slowest, good vs bad.

    uv run python tools/review_runs.py              # prints the review, writes runs/review.json + runs/best_paths.json

What it computes from runs/explore-*/transitions.jsonl and runs/milestones.json:
  goals     : per goal, every run that reached it, best/median steps, and the fastest SEGMENT (the exact button
              sequence from the previous goal to this one) -> runs/best_paths.json, which the planner can replay.
  waste     : per run, presses that achieved nothing (blocked moves, B loops, boxes that needed >N presses),
              split by source (agent / human / claude) so interventions are judged too.
  situations: per (map, x, y, facing, button) what happened historically: moved / blocked / warp / box opened,
              so the agent can prefer actions that worked and skip ones that never did.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

GOALS = ["potion", "left_house", "first_pokemon", "won_battle"]


def load_runs(root: Path):
    for d in sorted(root.glob("explore-*")):
        f = d / "transitions.jsonl"
        if f.exists():
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            if rows:
                yield d.name, rows


def goal_steps_for(run: str, milestones: dict) -> dict[str, int]:
    return {g: min(e["step"] for e in v if e["run"] == run) for g, v in milestones.items() if any(e["run"] == run for e in v)}


def main() -> int:
    root = Path("runs")
    ms = json.loads((root / "milestones.json").read_text()) if (root / "milestones.json").exists() else {}
    review = {"runs": {}, "goals": {}, "situations": {}}
    best_paths: dict[str, dict] = {}
    situations: dict[str, Counter] = defaultdict(Counter)

    for run, rows in load_runs(root):
        gs = goal_steps_for(run, ms)
        by_src = Counter(r.get("source", "agent") for r in rows)
        wasted = Counter()
        for r in rows:
            src = r.get("source", "agent")
            if r["button"] in ("UP", "DOWN", "LEFT", "RIGHT") and not r["moved"] and r["textbox"] == "none":
                wasted[src] += 1
            key = f"{r['from'][0]},{r['from'][1]},{r['from'][2]},{r.get('facing', '?')},{r['button']}"
            outcome = ("warp" if r["to"][0] != r["from"][0] else "moved" if r["moved"] else
                       "box" if r["textbox"] == "dialog" or r.get("text") else "blocked")
            situations[key][outcome] += 1
        review["runs"][run] = {"presses": len(rows), "by_source": dict(by_src), "goal_steps": gs,
                               "wasted_moves": dict(wasted), "waits": sum(1 for r in rows if r.get("waited"))}
        # fastest segment per goal: presses between the previous goal's step and this goal's step
        prev = 0
        for g in GOALS:
            if g in gs:
                seg = [r for r in rows if prev < r["step"] <= gs[g]]
                length = gs[g] - prev
                cur = best_paths.get(g)
                if cur is None or length < cur["length"]:
                    best_paths[g] = {"run": run, "length": length, "start": seg[0]["from"] if seg else None,
                                     "end": seg[-1]["to"] if seg else None,
                                     "buttons": [r["button"] for r in seg],
                                     "sources": dict(Counter(r.get("source", "agent") for r in seg))}
                prev = gs[g]

    for g in GOALS:
        hits = [(run, s[g]) for run, s in ((r, v["goal_steps"]) for r, v in review["runs"].items()) if g in s]
        if hits:
            steps = [s for _, s in hits]
            review["goals"][g] = {"runs_reached": len(hits), "best": min(steps), "median": statistics.median(steps),
                                  "worst": max(steps), "fastest_run": min(hits, key=lambda h: h[1])[0]}
    review["situations"] = {k: dict(v) for k, v in situations.items() if sum(v.values()) >= 2}
    never_worked = {k: v for k, v in review["situations"].items() if v.get("blocked", 0) >= 3 and len(v) == 1}
    review["never_worked"] = never_worked

    (root / "review.json").write_text(json.dumps(review, indent=1))
    (root / "best_paths.json").write_text(json.dumps(best_paths, indent=1))

    print(f"runs reviewed: {len(review['runs'])}")
    for g in GOALS:
        if g in review["goals"]:
            r = review["goals"][g]; bp = best_paths[g]
            print(f"  {g:14} reached in {r['runs_reached']} runs  best {r['best']:4}  median {r['median']:5}  worst {r['worst']:4}"
                  f"  | fastest segment {bp['length']} presses ({bp['sources']})")
        else:
            print(f"  {g:14} never reached")
    print(f"situations with history: {len(review['situations'])}; actions that NEVER worked (3+ tries): {len(never_worked)}")
    worst = sorted(review["runs"].items(), key=lambda kv: -sum(kv[1]["wasted_moves"].values()))[:3]
    for run, v in worst:
        print(f"  most waste: {run} wasted moves {v['wasted_moves']} of {v['presses']} presses")
    print("wrote runs/review.json and runs/best_paths.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
