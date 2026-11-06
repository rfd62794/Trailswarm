"""Done-condition status for PokeAgent: the numbers, not the logs.

    uv run python tools/status.py

Reads runs/milestones.json, runs/explore-*/meta.json and transitions.jsonl (all gitignored).
Prints the done-condition metrics; targets stay with Robert in DIRECTION.md.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.goals import GOALS, SIDE_GOALS

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
        if meta.get("stop_at_goal") != goal or meta.get("frame_share"):
            continue  # watched runs may play differently: they don't count for the done-condition
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


def _items_picked(d: Path) -> int:
    """Item-ball pickups in a run: positive bag deltas whose dialog said 'found/obtained <ITEM>!'."""
    n = 0
    for line in (d / "transitions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        it = rec.get("item")
        if not it or it.get("delta", 0) <= 0:
            continue
        text = f"{it.get('text', '')} {rec.get('text', '')}".lower()
        if "found" in text or "obtained" in text:
            n += 1
    return n


def interaction_lines(maps: dict) -> list[str]:
    """Defined-interaction metrics from maps.json: presses per type, re-talks avoided, heal visits, frames per text page."""
    st = maps.get("interaction_stats") or {}
    out = []
    by = st.get("by_type", {})
    if by:
        out.append("interactions by type (talks, mean presses): " + ", ".join(
            f"{k} {v['talks']}x {v['presses'] / max(1, v['talks']):.1f}" for k, v in sorted(by.items())))
    if st:
        out.append(f"re-talks avoided: {st.get('retalks_avoided', 0)}; info/sign re-talked: {st.get('retalks', 0)}; "
                   f"heal visits: {st.get('heal_visits', 0)}")
    tp = maps.get("text_press_stats")
    if tp and tp.get("pages"):
        out.append(f"text pace: {tp['frames'] / tp['pages']:.1f} frames/page, {tp['presses'] / tp['pages']:.2f} presses/page, "
                   f"{tp.get('dropped', 0)} dropped; speed byte {(maps.get('text_speed') or {}).get('byte', '?')}")
    return out


def _trainee_line(dirs: list[Path]) -> str:
    """Newest run that recorded Magikarp numbers (meta.json "magikarp") plus the background goals (SIDE_GOALS)."""
    for d in reversed(dirs):
        meta = _meta(d)
        mk = meta.get("magikarp")
        if mk is None:
            continue
        side = ", ".join(f"{g}={'yes' if meta.get('side_goals', {}).get(g) else 'no'}" for g in SIDE_GOALS)
        lvl = f"L{mk['level']}" if "level" in mk else "not owned"
        return (f"magikarp ({d.name}): {lvl}, battles shared {mk.get('battles_shared', 0)} of {mk.get('battles', 0)}; "
                f"background goals: {side}")
    return "magikarp: no run has bought one yet; background goals: " + ", ".join(f"{g}=no" for g in SIDE_GOALS)


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

    for line in interaction_lines(maps):
        print(line)

    dirs = _run_dirs()
    if dirs:
        from backtrack_report import backtrack_stats
        s = backtrack_stats(dirs[-1] / "transitions.jsonl")
        print(f"backtrack ({dirs[-1].name}): reversals {s['reversal_pct']:.1f}% ({s['reversals']}/{s['moves']} agent moves), "
              f"back-in-2 {s['back2_pct']:.1f}% ({s['back_in_2']}/{s['moves']})")
        print(f"items picked up ({dirs[-1].name}): {_items_picked(dirs[-1])}")
    print(_trainee_line(dirs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
