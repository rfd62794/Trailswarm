"""Which (state, build) starts a segment or a drill: Go-Explore over the library's (name, build) cells.

Three modes, drawn from SHARES: ``exploit`` = the best build by recorded metrics (the best build at the
furthest checkpoint - the caller picks for the segment the curriculum already chose), ``alternative`` = a
rarity-weighted draw over the non-exploit cells so rarely-tried builds win, ``promising`` = an under-tried
build with the best readiness. Deterministic for the caller's seeded ``rng`` (never the global random);
``None`` when no clean cell matches, so the caller falls back to today's checkpoint/newest-state path.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from pokeagent.goexplore import select
from pokeagent.statelib import cells

SHARES = {"exploit": 0.60, "alternative": 0.25, "promising": 0.15}   # untuned first values
PROMISING_MIN_TRIES = 3                                             # "under-tried" threshold (untuned)
SHARES_FILE = Path("runs/curriculum_builds.json")


@dataclass(frozen=True)
class Pick:
    state: str            # the library's state path (relative to the run root)
    build: str | None
    cell: str             # cells.cell_id of the chosen entry
    mode: str             # "exploit" | "alternative" | "promising"
    why: str              # one-line explanation for the curriculum log line and the job record


def load_shares(root) -> dict:
    """The mode shares, overridable by runs/curriculum_builds.json {"shares": {...}} (read once per call;
    a missing or malformed file means the SHARES defaults)."""
    try:
        s = json.loads((Path(root) / SHARES_FILE).read_text(encoding="utf-8")).get("shares")
        if isinstance(s, dict) and all(isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool)
                                       and s[k] >= 0 for k in SHARES) and sum(s[k] for k in SHARES) > 0:
            return {k: float(s[k]) for k in SHARES}
    except (OSError, ValueError, AttributeError):
        pass
    return dict(SHARES)


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _exploit_key(e: dict) -> tuple:
    """(readiness desc, steps asc, faints asc), nulls last: the best build at this checkpoint."""
    m = e.get("metrics") or {}
    r, s, f = _num(m.get("readiness")), _num(m.get("steps")), _num(m.get("faints"))
    return (r if r is not None else -1e30, -(s if s is not None else 1e30), -(f if f is not None else 1e30))


def _pick(e: dict, mode: str, tries: dict) -> Pick:
    cid = cells.cell_id(e)
    n = cells.tries_of(tries, cid)
    r = _num((e.get("metrics") or {}).get("readiness"))
    why = (f"build {e.get('build') or 'unknown'}, mode {mode}, {n} {'try' if n == 1 else 'tries'}, "
           f"readiness {round(r, 3) if r is not None else '?'}")
    return Pick(str(e.get("state") or ""), e.get("build"), cid, mode, why)


def _mode(shares: dict, rng: random.Random) -> str:
    r = rng.random() * sum(float(shares.get(k) or 0.0) for k in SHARES)
    acc = 0.0
    for m in SHARES:
        acc += float(shares.get(m) or 0.0)
        if r < acc:
            return m
    return "promising"


def pick_start(entries, segment_start: str, rng: random.Random, tries: dict, shares=SHARES) -> Pick | None:
    """The start state for the segment (or leg) that begins at ``segment_start``: candidates are the clean
    cells whose ``name`` equals it. ``None`` when there are none - the caller keeps today's fallback."""
    cands = [e for e in entries or ()
             if isinstance(e, dict) and e.get("name") == segment_start and cells.is_cell(e)]
    if not cands:
        return None
    best = max(cands, key=_exploit_key)
    mode = "exploit" if len({e.get("build") for e in cands}) == 1 else _mode(shares or SHARES, rng)
    if mode == "exploit":
        return _pick(best, mode, tries)
    if mode == "promising":
        young = [e for e in cands if cells.tries_of(tries, cells.cell_id(e)) < PROMISING_MIN_TRIES]
        if young:
            def key(e):
                r = _num((e.get("metrics") or {}).get("readiness"))
                return (r if r is not None else -1e30, _exploit_key(e))
            return _pick(max(young, key=key), mode, tries)
        mode = "alternative"   # nothing under-tried: promising falls back to alternative
    rest = [e for e in cands if e is not best]                          # alternative: over the NON-exploit cells
    if not rest:
        return _pick(best, "exploit", tries)
    got = next((e for e in rest if cells.cell_id(e) ==
                select.choose(cells.to_archive(rest, {}, tries=tries), rng)), None)
    return _pick(got or best, mode, tries)
