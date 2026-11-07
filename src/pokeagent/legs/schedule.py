"""Which leg to drill next: the worst by waste = samples x (median - par), among legs with enough samples and an entry state,
skipping legs retired for a while after hitting par twice. Pure over legs.json / drills.jsonl / the states directory."""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.legs import states as S
from pokeagent.legs.drill import DRILLS_LOG, budget_steps
from pokeagent.legs.drill_fold import hit_par, load_drills, matches

MIN_SAMPLES = 3
RETIRE_HITS = 2
RETIRE_S = 7 * 86400   # a leg that hit par twice rests for a week


def waste(rec: dict) -> float:
    return rec["samples"] * (rec["median_frames"] - rec["par_frames"])


def retired(rec: dict, drills: list[dict], now: float) -> bool:
    """RETIRE_HITS solved-at-par drills of this leg, the latest within RETIRE_S."""
    hits = [d for d in drills if matches(rec, d) and hit_par(d)]
    return len(hits) >= RETIRE_HITS and now - max(d.get("t", 0) for d in hits) < RETIRE_S


def rank(legs: dict, states: set, drills: list[dict], now: float, min_samples: int = MIN_SAMPLES) -> list[dict]:
    """Drillable leg records, worst first."""
    ok = [r for r in legs.values()
          if r.get("par_frames") is not None and r["samples"] >= min_samples and (r["map"], *r["entry"]) in states
          and waste(r) > 0 and not retired(r, drills, now)]
    return sorted(ok, key=lambda r: -waste(r))


def pick(root: str | Path, n: int = 0, now: float | None = None, states_dir: str | Path | None = None) -> dict | None:
    """The n-th worst drillable leg as a launch config {leg, state, steps, key}; None when there is nothing to drill.
    Rotating on n spreads concurrent slots over different legs."""
    root = Path(root)
    try:
        legs = json.loads((root / "runs" / "legs.json").read_text(encoding="utf-8")).get("legs", {})
    except (OSError, ValueError):
        return None
    sd = Path(states_dir) if states_dir else root / S.STATES_DIR
    ranked = rank(legs, S.keys(sd), load_drills(root / DRILLS_LOG), time.time() if now is None else now)
    if not ranked:
        return None
    r = ranked[n % min(len(ranked), 5)]
    state = S.newest(sd, r["map"], *r["entry"])
    if state is None:
        return None
    from pokeagent.legs.drill import DrillSpec
    spec = DrillSpec(r["map"], tuple(r["entry"]), tuple(r["exit"]), r.get("button", ""))
    return {"leg": spec.text, "state": str(state), "steps": budget_steps(r["par_frames"]), "key": r["key"]}
