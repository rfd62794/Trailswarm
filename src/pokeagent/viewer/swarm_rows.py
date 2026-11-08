"""Swarm page data: one row per agent/slot, assembled from the model cache plus run files.

Pure (no UI imports): small file readers + ``build_rows`` -> a list of row dicts for
``ui/swarm_page``. ``SwarmRowStore`` holds the last assembly; the poll thread refreshes it at
1 Hz, the render thread only calls ``rows()``. File contents: ``runs/segments.json`` (the
curriculum the supervisor writes, read-only via seg_store; per-segment grades computed live
through ``pokeagent.segment_grades``), ``runs/swarm/agent_stats.jsonl`` (Agent_Footprint's
per-agent RSS + steps/s; blanks while absent).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

from pokeagent.viewer.health_classify import Health, OK

_log = logging.getLogger(__name__)
_logged: set[str] = set()   # fallback messages already warned about: a 1 Hz caller must not spam

NA = "n/a"
STATS_TAIL = 400                     # jsonl lines scanned from the end of agent_stats.jsonl
ROW_KEYS = ("id", "state", "segment", "grade", "next", "steps_s", "rss", "health", "reason", "goal")
_OK = Health(OK, "")


def _warn_once(msg: str) -> None:
    """log.warning once per distinct message; rows still assemble but the blank is never silent."""
    if msg not in _logged:
        _logged.add(msg)
        _log.warning(msg)


def _seg_store():
    """tools/seg_store.py, lazily - the same tools/-on-sys.path shim ``review/segments.py`` uses,
    centralised in this one helper so the doc readers below AND ``segment_grades``' own lazy
    ``import seg_store`` share it. None (warned once) when the tools dir/module is absent."""
    d = Path(__file__).resolve().parents[3] / "tools"
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    try:
        import seg_store
    except ImportError as e:
        _warn_once(f"swarm rows: seg_store unavailable ({e}); segment/next/grade columns blank")
        return None
    return seg_store


def _segments_doc(root: Path) -> dict:
    ss = _seg_store()
    if ss is None:
        return {}
    try:
        return ss.load(root)
    except (OSError, ValueError, TypeError) as e:
        # a torn read while the supervisor saves is a legitimate blank; the type spread is what
        # seg_store.load raises on a missing/corrupt/non-object file - say so once, blank this tick
        _warn_once(f"swarm rows: segments.json unreadable ({type(e).__name__}: {e}); blanks this tick")
        return {}


def _layout_keys(doc: dict) -> list[str]:
    """The curriculum's leaf segments in chain order ([] when the store cannot be read)."""
    ss = _seg_store()
    if ss is None:
        return []
    try:
        return [s.key for s in ss.layout(doc)]
    except (KeyError, TypeError, AttributeError) as e:   # what layout() raises on a malformed doc
        _warn_once(f"swarm rows: segment layout unreadable ({type(e).__name__}: {e})")
        return []


def _grades(doc: dict, root: Path) -> dict:
    """segment key -> scorecard ``Grade``: one ``grade_all`` per refresh (the 1 Hz cadence)."""
    if _seg_store() is None:   # also primes sys.path for segment_grades' lazy seg_store import
        return {}
    try:
        from pokeagent import segment_grades as sg
        return {g.key: g for g in sg.grade_all(doc, root, time.time())}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        # ImportError: the scorecard module/tools absent; the rest: malformed stats in a torn or
        # foreign doc surface as these through seg_store's readers - never a crash, never silent
        _warn_once(f"swarm rows: grade_all failed ({type(e).__name__}: {e}); grade column n/a")
        return {}


def next_segment(keys: list[str], current: str) -> str:
    """The curriculum leaf after ``current`` ('' when unknown or last); a plain goal id also
    answers for a split key like ``to_route1@0c`` (falls back to the goal's leaf)."""
    if not current or current == NA:
        return ""
    i = keys.index(current) if current in keys else (keys.index(current.split("@", 1)[0])
                                                     if current.split("@", 1)[0] in keys else -1)
    return keys[i + 1] if 0 <= i < len(keys) - 1 else ""


def _grade_word(g) -> str:
    """The grade cell for a scorecard Grade: the flag words ``pokeagent review segments`` prints."""
    f = []
    if g.held:
        f.append(f"held({g.held})")
    if g.solved:
        f.append("solved")
    if g.optimized:
        f.append("optimized")
    if g.stale:
        f.append("stale")
    if g.broken:
        f.append("BROKEN")
    if g.synthetic_only:
        f.append("synth?")
    return ",".join(f) or "-"


def _grade(gmap: dict, segment: str) -> str:
    """The scorecard's flags for the segment (``n/a`` while no grade can be computed)."""
    if not segment or segment == NA:
        return NA
    g = gmap.get(segment) or gmap.get(segment.split("@", 1)[0])
    if g is None or (g.last_ts is None and not g.attempts):
        return NA  # no scorecard data at all reads n/a; the grader's "stale" is for data that went old
    return _grade_word(g)


def _agent_stats(root: Path) -> dict[str, dict]:
    """Latest ``runs/swarm/agent_stats.jsonl`` row per agent id and per ``pid:<n>`` ({} absent)."""
    try:
        lines = (Path(root) / "runs" / "swarm" / "agent_stats.jsonl").read_text(encoding="utf-8") \
            .splitlines()[-STATS_TAIL:]
    except OSError:
        return {}
    out: dict[str, dict] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            if row.get("agent") is not None:
                out[str(row["agent"])] = row
            if row.get("pid") is not None:
                out[f"pid:{row['pid']}"] = row
    return out


def _num(v) -> str:
    try:
        return "" if v is None else f"{float(v):g}"
    except (TypeError, ValueError):
        return ""


def _last_goal(snap) -> str:
    """The most recent goal the agent landed (its goals list, newest-done last)."""
    if snap is None:
        return ""
    done = [g.name or g.id for g in snap.goals if g.status == "done"]
    return done[-1] if done else ""


def _state(staleness: str, has_entry: bool) -> str:
    """live -> live; stale (heartbeat overdue) -> lost; lost (10 s silent) or registry gone -> dead."""
    if not has_entry:
        return "dead"
    return {"live": "live", "stale": "lost"}.get(staleness, "dead")


def build_rows(root: Path, ids: list[str], staleness, snapshot_for, entries: dict, health_for) -> list[dict]:
    """One row per known agent (model ids ∪ registry entries, sorted). ``staleness``/``snapshot_for``/
    ``health_for`` are the model/HealthStore lookups (or test lambdas); files are read once per call."""
    doc = _segments_doc(root)
    keys = _layout_keys(doc)
    gmap = _grades(doc, Path(root))
    stats = _agent_stats(root)
    id_set = set(ids)
    rows: list[dict] = []
    for aid in sorted(id_set | set(entries or {})):
        snap = snapshot_for(aid)
        e = (entries or {}).get(aid) or {}
        seg = (snap.segment.id or NA) if snap is not None else NA
        ast = stats.get(aid) or stats.get(f"pid:{e.get('pid')}") or {}
        h = health_for(aid) or _OK
        rows.append({"id": aid, "state": _state(staleness(aid), bool(e) or aid in id_set),
                     "segment": seg, "grade": _grade(gmap, seg),
                     "next": next_segment(keys, seg) or NA,
                     "steps_s": _num(ast.get("steps_per_s")), "rss": _num(ast.get("rss_mb")),
                     "health": h.state, "reason": h.reason, "goal": _last_goal(snap)})
    return rows


class SwarmRowStore:
    """The last ``build_rows`` result; refreshed on the poll thread, read (a copy) on the render thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict] = []

    def refresh(self, root: Path, model, entries: dict, health) -> None:
        health_for = health.health if health is not None else (lambda _aid: _OK)
        rows = build_rows(Path(root), model.ids(), model.staleness, model.snapshot, entries, health_for)
        with self._lock:
            self._rows = rows

    def rows(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._rows]
