"""``pokeagent review segments``: the segment scorecard - grades, effective shares, rejoin candidates.

Reads runs/segments.json (and optionally ingests finished runs first), grades every segment through
``pokeagent.segment_grades``, and returns one JSON-able dict the text renderer prints. Read-only on
the checkout by default; --ingest opts into the same locked ingest+save the curriculum does.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_log = logging.getLogger(__name__)
_logged: set[str] = set()   # fallback messages already warned about: a frequent caller does not spam


def _warn_once(msg: str) -> None:
    """log.warning once per distinct message; a grade fallback keeps working but is never silent."""
    if msg not in _logged:
        _logged.add(msg)
        _log.warning(msg)


def _tools():
    """tools/ holds the curriculum modules (seg_store, seg_ingest, seg_hold, seg_split, seg_suites)."""
    d = ROOT / "tools"
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))


def _load_mods():
    _tools()
    import seg_hold       # noqa: E402
    import seg_ingest     # noqa: E402
    import seg_split      # noqa: E402
    import seg_store      # noqa: E402
    import seg_suites     # noqa: E402
    from pokeagent import segment_grades as sg  # noqa: E402
    return sg, seg_store, seg_ingest, seg_hold, seg_split, seg_suites


def _grids():
    try:
        from pokeagent.legs.grid import rom_grids
        return rom_grids()
    except Exception as e:  # noqa: BLE001 - rom_grids() is opaque (ROM decode): no ROM -> no par, never a crash
        _warn_once(f"review segments: no ROM grids ({type(e).__name__}: {e})")
        return None


def _frontier(ss, root, doc):
    """The segment the scheduler would call the frontier (same rule as Curriculum.groups)."""
    nxt = next((s for s in ss.layout(doc) if not ss.ckpt_valid(root, s.end)), None)
    if nxt is not None and ss.ckpt_valid(root, nxt.start):
        return nxt.key
    return None


def summarise(root: Path, suite: str | None = None, do_ingest: bool = False, now: float | None = None) -> dict:
    """The whole scorecard as JSON-able data. Raises ValueError on an unknown suite name. Read-only
    unless do_ingest: then the ingest runs under ss.locked, the same segments.json transaction the
    curriculum's Curriculum.txn takes, so a supervisor's write is never clobbered."""
    sg, ss, seg_ingest, seg_hold, seg_split, seg_suites = _load_mods()
    root = Path(root)
    now = time.time() if now is None else now
    if do_ingest:
        with ss.locked(root) as doc:      # read-modify-write under the store lock, like Curriculum.txn
            seg_ingest.ingest(root, doc)
    else:
        doc = ss.load(root)
    grades = sg.grade_all(doc, root, now, par_fn=sg.make_par_fn(root, _grids()),
                          hold_file=seg_hold.HoldFile(root))
    gmap = {g.key: g for g in grades}
    eff = sg.effective_shares(grades)
    fkey = _frontier(ss, root, doc)
    fh = sg.frontier_health(gmap.get(fkey))
    # per-segment share: its group's effective share spread over the group's candidates
    group = {}
    for g in grades:
        if g.held:
            group[g.key] = None
        elif g.key == fkey:
            group[g.key] = "frontier"
        elif sg.solved_effective(g) and not g.broken:
            group[g.key] = "polish"
        else:
            group[g.key] = "unsolved"
    counts = {k: sum(1 for v in group.values() if v == k) for k in eff}
    share = {k: (eff[group[k]] / counts[group[k]] if group[k] else 0.0) for k in group}
    rejoin = [goal for goal in doc["splits"]
              if seg_split.should_rejoin(doc, goal, grades, [s for s in ss.layout(doc) if s.goal == goal])]
    members = None
    if suite:
        members = seg_suites.resolve(suite, doc, grades, root)
        if members is None:
            raise ValueError(f"unknown or malformed suite {suite!r}")
        members = [m["key"] for m in members]
    rows = []
    for g in grades:
        if members is not None and g.key not in members:
            continue
        st = ss.stat(doc, g.key)
        rows.append({"segment": g.key, "tries": g.attempts, "rate": g.rate,
                     "solved": g.solved, "optimized": g.optimized, "stale": g.stale, "broken": g.broken,
                     "held": g.held, "synthetic_only": g.synthetic_only, "provenance": g.provenance,
                     "best": g.best, "par": g.par, "expected": g.expected, "health": g.health,
                     "blackout_rate": g.blackout_rate, "stall_rate": g.stall_rate, "loop_rate": g.loop_rate,
                     "start": g.start, "share": share[g.key],
                     "cut_hints": seg_split.cut_hints(st, root),
                     "last_ts": g.last_ts, "sha_before": g.sha_before, "sha_after": g.sha_after})
    return {"root": str(root), "generated_at": now, "rows": rows, "shares": eff,
            "frontier": fkey, "frontier_health": fh,
            "explore_rate": sg.explore_for_health(fh), "rejoin_candidates": rejoin,
            "suite": suite, "suites": sorted(seg_suites.load_suites(root)),
            "broken": any(r["broken"] and not r["held"] for r in rows)}
