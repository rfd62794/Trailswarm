"""Done-condition status for PokeAgent: the numbers, not the logs.

    uv run python tools/status.py

Reads runs/milestones.json, runs/explore-*/meta.json and transitions.jsonl (all gitignored).
Prints the done-condition metrics; targets stay with Robert in DIRECTION.md.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.goals import GOALS

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _run_dirs() -> list[Path]:
    if not RUNS.exists():
        return []
    return [d for d in sorted(RUNS.glob("explore-*"), key=lambda p: p.stat().st_mtime)
            if (d / "transitions.jsonl").exists()]


def _meta(d: Path) -> dict:
    return _load_json(d / "meta.json", {})


def _start_index(meta: dict) -> int | None:
    st = meta.get("start", "baseline")
    if st in ("baseline", "bedroom", None):
        return -1
    if st in GOALS:
        return GOALS.index(st)
    if st == "team_best":
        return GOALS.index("to_route1")
    return None


def _segment_attempts(goal: str, last_n: int = 24) -> tuple[int, int]:
    """(successes, attempts) for `goal` over its most recent `last_n` segment runs.

    Only runs launched with `--stop-at-goal <goal>` count, so roles/full runs do not
    dilute the rate (the overnight consistency window has that dilution problem).
    """
    i = GOALS.index(goal)
    ms = _load_json(RUNS / "milestones.json", {})
    reached = {e["run"] for e in ms.get(goal, [])}
    tries: list[str] = []
    for d in _run_dirs():
        meta = _meta(d)
        if meta.get("stop_at_goal") != goal:
            continue
        si = _start_index(meta)
        started = set(meta.get("initial_goals", []))
        if si is not None and si < i and goal not in started:
            tries.append(d.name)
    tries = tries[-last_n:]
    return sum(1 for r in tries if r in reached), len(tries)


def _unbroken_badge_run(ms: dict) -> dict | None:
    """First full run (no segment stop, started at the baseline) that reached beat_brock."""
    for d in _run_dirs():
        meta = _meta(d)
        if _start_index(meta) != -1 or meta.get("stop_at_goal"):
            continue
        if "beat_brock" in set(meta.get("initial_goals", [])):
            continue
        if not any(e["run"] == d.name for e in ms.get("beat_brock", [])):
            continue
        consults = human = presses = 0
        for line in (d / "transitions.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            presses += 1
            src = json.loads(line).get("source", "agent")
            if src == "claude":
                consults += 1
            elif src == "human":
                human += 1
        return {"run": d.name, "presses": presses, "claude_consults": consults, "human_presses": human}
    return None


def main() -> int:
    if not RUNS.exists():
        print("no runs/ data in this checkout (runs/ is gitignored; run the swarm here first)")
        return 0
    ms = _load_json(RUNS / "milestones.json", {})
    print("PokeAgent done-condition status")
    print("targets: unset (Robert sets them in DIRECTION.md); numbers below are measured")

    succ, att = _segment_attempts("beat_brock", 24)
    rate = f" ({succ / att:.0%})" if att else ""
    print(f"beat_brock segment: {succ}/{att} attempts succeeded{rate}")

    run = _unbroken_badge_run(ms)
    if run:
        print(f"unbroken bedroom->badge run: {run['run']} presses={run['presses']} "
              f"claude_consults={run['claude_consults']} human_presses={run['human_presses']}")
    else:
        print("unbroken bedroom->badge run: none found")

    readme = (ROOT / "README.md").exists()
    writeups = sorted(p.name for p in list(ROOT.glob("*WRITEUP*")) + list(ROOT.glob("*writeup*"))
                      + list((ROOT / "docs").glob("*WRITEUP*")) + list((ROOT / "docs").glob("*writeup*")))
    print(f"README: {'present' if readme else 'MISSING'}; writeup: {', '.join(writeups) if writeups else 'not found'}")

    maps = _load_json(RUNS / "maps.json", {})
    tiles = sum(len(m.get("visited", {})) for m in maps.get("maps", {}).values())
    print(f"world: {len(maps.get('maps', {}))} maps, {tiles} tiles, team_best_level={maps.get('team_best_level', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
