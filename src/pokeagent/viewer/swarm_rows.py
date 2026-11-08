"""Swarm page data: one row per agent/slot, assembled from the model cache plus run files.

Pure (no UI imports): small file readers + ``build_rows`` -> a list of row dicts for
``ui/swarm_page``. ``SwarmRowStore`` holds the last assembly; the poll thread refreshes it at
1 Hz, the render thread only calls ``rows()``. File contents: ``runs/segments.json`` (the
curriculum the supervisor writes, read-only via seg_store), ``runs/swarm/agent_stats.jsonl``
(Agent_Footprint's per-agent RSS + steps/s; blanks while absent).
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from pokeagent.viewer.health_classify import Health, OK

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
try:
    import seg_store as _ss          # the scorecard reader (tools/, not a package)
except Exception:                    # pragma: no cover - tools dir absent: rows still assemble
    _ss = None

NA = "n/a"
STATS_TAIL = 400                     # jsonl lines scanned from the end of agent_stats.jsonl
ROW_KEYS = ("id", "state", "segment", "grade", "next", "steps_s", "rss", "health", "reason", "goal")
_OK = Health(OK, "")


def _segments_doc(root: Path) -> dict:
    try:
        return _ss.load(root) if _ss is not None else {}
    except Exception:                # a torn write while the supervisor saves: blanks this tick
        return {}


def _layout_keys(doc: dict) -> list[str]:
    """The curriculum's leaf segments in chain order ([] when the store cannot be read)."""
    try:
        return [s.key for s in _ss.layout(doc)] if _ss is not None else []
    except Exception:
        return []


def next_segment(keys: list[str], current: str) -> str:
    """The curriculum leaf after ``current`` ('' when unknown or last); a plain goal id also
    answers for a split key like ``to_route1@0c`` (falls back to the goal's leaf)."""
    if not current or current == NA:
        return ""
    i = keys.index(current) if current in keys else (keys.index(current.split("@", 1)[0])
                                                     if current.split("@", 1)[0] in keys else -1)
    return keys[i + 1] if 0 <= i < len(keys) - 1 else ""


def _grade(doc: dict, segment: str) -> str:
    """The scorecard's grade for the segment (``n/a`` until the scorecard lands one)."""
    if not segment or segment == NA:
        return NA
    stats = doc.get("stats") or {}
    st = stats.get(segment) or stats.get(segment.split("@", 1)[0]) or {}
    g = st.get("grade")
    return NA if g is None else str(g)


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
                     "segment": seg, "grade": _grade(doc, seg),
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
