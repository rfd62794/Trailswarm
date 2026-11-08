"""Measured grind economics: real frames-per-step and real XP from run records (not xp_estimates.jsonl).

transitions.jsonl rows carry ``step``/``moved``/``source`` but no frame counter; levels.jsonl rows carry
``step``/``frame`` (and the party with the RAM-read exp total). Both are used here: transitions rows that
carry a ``frame`` field win, else the (step, frame) pairs of levels.jsonl. Pure file reading; never raises
on missing data ({}-style answers instead).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import median

log = logging.getLogger(__name__)

FRAMES_PER_STEP_DEFAULT = 16.0   # the old atlas ASSUMPTION, kept as the fallback when no runs are readable
LAST_RUNS = 20                   # calibration window: the newest run directories
AGENT = "agent"
RUNS_ROOT = Path(__file__).resolve().parents[3] / "runs"  # the checkout's runs dir (explore_demo/the swarm's), never the cwd
_warned: set = set()


def _warn_once(key: str, msg: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        log.info(msg, *args)


def read_jsonl(path: Path):
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError as e:
                _warn_once(f"jsonl:{path.name}", "grind measure: skipping a bad line in %s (%r)", path, e)
                continue
            if isinstance(r, dict):
                yield r
    except OSError:
        return


_jsonl = read_jsonl  # private name kept for the PR #165 callers


def _pair_rates(rows) -> list[float]:
    """(frame delta / step delta) between consecutive (step, frame) rows."""
    pairs = [(int(r["step"]), int(r["frame"])) for r in rows
             if isinstance(r.get("step"), (int, float)) and isinstance(r.get("frame"), (int, float))]
    return [(f2 - f1) / (s2 - s1) for (s1, f1), (s2, f2) in zip(pairs, pairs[1:]) if s2 > s1 and f2 > f1]


def frames_per_step(transition_rows, levels_rows=None) -> float | None:
    """Median frames per agent step. Transitions carrying ``frame`` are used directly (delta between
    consecutive moved agent presses); otherwise the run's ``levels.jsonl`` (step, frame) pairs give the rate."""
    rows = [r for r in transition_rows if r.get("moved") and r.get("source", AGENT) == AGENT]
    if rows and isinstance(rows[0].get("frame"), (int, float)):
        deltas = [b["frame"] - a["frame"] for a, b in zip(rows, rows[1:])
                  if isinstance(b.get("frame"), (int, float)) and b["frame"] > a["frame"]]
        return float(median(deltas)) if deltas else None
    rates = _pair_rates(levels_rows or [])
    return float(median(rates)) if rates else None


def run_frames_per_step(run_dir: Path) -> float | None:
    """One run's frames/step from its transitions.jsonl (falling back to its levels.jsonl pairs)."""
    run_dir = Path(run_dir)
    return frames_per_step(list(_jsonl(run_dir / "transitions.jsonl")), list(_jsonl(run_dir / "levels.jsonl")))


def calibration(runs_dir: str | Path = RUNS_ROOT, last: int = LAST_RUNS) -> tuple[float | None, int]:
    """(median frames/step, runs sampled) over the newest ``last`` run directories that have a press log."""
    runs = Path(runs_dir)
    if not runs.is_dir():
        return None, 0
    # One directory listing (names embed the timestamp), then stat ONLY the newest ``last`` names:
    # the live checkout's runs/ holds 4,700+ run dirs (PR #165 review - never stat them all).
    dirs = [p for n in sorted(d.name for d in runs.iterdir())[-last:]
            if (p := runs / n).is_dir() and (p / "transitions.jsonl").exists()]
    rates: list[float] = []
    for d in dirs:
        fps = run_frames_per_step(d)
        if fps is not None:
            rates.append(fps)
    return (float(median(rates)), len(rates)) if rates else (None, 0)


def frames_per_step_or_default(runs_dir: str | Path = RUNS_ROOT, default: float = FRAMES_PER_STEP_DEFAULT,
                               last: int = LAST_RUNS) -> float:
    """The calibrated frames/step, else ``default`` (logged once: the caller cannot tell a quiet 16 apart
    from a measured one otherwise)."""
    fps, n = calibration(runs_dir, last)
    if fps is None:
        _warn_once("fps-default", "grind measure: no run records under %s; assuming %g frames/step",
                   runs_dir, default)
        return default
    return fps


def xp_gained_in_episode(levels_rows, start_step: int, end_step: int) -> int:
    """MEASURED party exp gained between two steps: the exp-total delta of the last levels.jsonl row at or
    before each bound. ``party`` entries are ``[species, level, exp, hp, max_hp]`` (RAM-read, not estimated)."""
    rows = [r for r in levels_rows if isinstance(r.get("step"), (int, float)) and r.get("party")]
    if not rows:
        return 0

    def exp_of(r) -> int:
        return sum(int(m[2]) for m in r["party"] if len(m) > 2 and isinstance(m[2], (int, float)))

    before = next((r for r in reversed(rows) if r["step"] <= start_step), rows[0])
    after = next((r for r in reversed(rows) if r["step"] <= end_step), rows[-1])
    return max(0, exp_of(after) - exp_of(before))
