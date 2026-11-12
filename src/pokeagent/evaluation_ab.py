"""Pure helpers for tools/ab.py: per-run metrics from a run dir, summary stats, paired sign test.

Metrics come from ``decisions.jsonl`` (one record per press; ``event`` lines are bandit/anomaly extras) and
``goal_frames.jsonl`` (one line per goal reached: goal, step, frame). Blackouts are only visible as ``event: blackout``
lines (written when the bandit is on), so a run without the bandit reports 0.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

NO_PROGRESS_WINDOW = 600  # presses without a new tile = one stall


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def extract_metrics(run_dir: Path | str, goal: str, cap: int | None = None) -> dict:
    """Metrics for one run. ``steps``/``frames`` are None when the goal was not reached."""
    run_dir = Path(run_dir)
    lines = _lines(run_dir / "decisions.jsonl")
    presses = [d for d in lines if "event" not in d]
    events = [d for d in lines if "event" in d]
    hit = next((g for g in _lines(run_dir / "goal_frames.jsonl") if g.get("goal") == goal and not g.get("skipped")), None)
    seen, since_new, window_stalls = set(), 0, 0
    for d in presses:
        tile = (d.get("map"), d.get("x"), d.get("y"))
        if tile in seen:
            since_new += 1
            if since_new >= NO_PROGRESS_WINDOW:
                window_stalls, since_new = window_stalls + 1, 0
        else:
            seen.add(tile)
            since_new = 0
    battles = sum(1 for prev, cur in zip([{}] + presses, presses) if cur.get("battle") and not prev.get("battle"))
    return {"solved": hit is not None, "steps": hit["step"] if hit else None, "frames": hit["frame"] if hit else None,
            "presses": len(presses), "cap": cap,
            "stalls": sum(d.get("rule") == "stall_escalate" for d in presses) + window_stalls,
            "blackouts": sum(e.get("event") == "blackout" for e in events), "battles": battles,
            "item_tossed": sum(e.get("event") == "item_tossed" for e in events)}


def effective_steps(m: dict, cap: int) -> int:
    return m["steps"] if m.get("solved") and m.get("steps") is not None else cap  # unsolved counts as the step cap


def sign_test_p(diffs: list[float]) -> float:
    """Two-sided exact sign test p-value; zero differences are dropped."""
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    k = min(sum(d > 0 for d in nz), sum(d < 0 for d in nz))
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def summarize(runs_a: list[dict], runs_b: list[dict], cap: int) -> dict:
    """Solve rate, median steps over solved runs, paired (B - A, unsolved = cap) difference and sign test when n >= 5."""
    def side(runs):
        solved = [r["steps"] for r in runs if r["solved"]]
        return {"n": len(runs), "solved": len(solved), "solve_rate": len(solved) / len(runs) if runs else 0.0,
                "median_steps": statistics.median(solved) if solved else None}
    diffs = [effective_steps(b, cap) - effective_steps(a, cap) for a, b in zip(runs_a, runs_b)]
    n = len(diffs)
    return {"a": side(runs_a), "b": side(runs_b), "paired_diffs": diffs,
            "mean_diff": statistics.mean(diffs) if diffs else None, "median_diff": statistics.median(diffs) if diffs else None,
            "p_value": sign_test_p(diffs) if n >= 5 else None,
            "test": "sign test" if n >= 5 else "too few seeds"}
