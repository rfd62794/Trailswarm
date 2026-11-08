"""Pure health classification: run-name joins and anomaly > stalled > slow > ok (no file I/O).

Split from ``health.py`` (which keeps the readers and the store) to stay under the module size cap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

JOIN_SLACK_S = 120            # untuned first value: a run joins an agent if it started >= agent.started - this
STALL_FRESH_S = 900           # untuned first value: a dossier this new makes the card "stalled"
STALL_SLOW_S = 3600           # untuned first value: an older dossier (up to this) leaves the card "slow"
ANOMALY_FRESH_S = 600         # untuned first value: an anomaly this new makes the card "anomaly" (top priority)
HEALTH_POLL_S = 1.0           # the refresh cadence on the poll thread (<= 1 Hz)
INVARIANT_EVERY_S = 60.0      # untuned first value: how often the one-shot worker re-runs run_all

OK, SLOW, STALLED, ANOMALY = "ok", "slow", "stalled", "anomaly"

_RUN_TAIL = re.compile(r"(?P<day>\d{8})-(?P<hms>\d{6})-(?P<pid>\d+)$")


@dataclass(frozen=True)
class AnomalyRef:
    run: str
    step: int
    type: str
    png: Path | None
    state: Path | None
    mtime: float
    cause_hint: str = ""
    provenance: str = ""        # from the anomalies.jsonl row; "" when absent


@dataclass(frozen=True)
class Health:
    state: str
    reason: str
    anomaly: AnomalyRef | None = None
    dossier_run: str | None = None


def run_pid(run: str) -> str | None:
    """``"explore-20261107-153827-24324"`` -> ``"24324"``; None when the name does not end ``-<pid>``."""
    tail = str(run).rsplit("-", 1)[-1]
    return tail if tail.isdigit() else None


def _run_started(run: str) -> float | None:
    """Epoch of the ``YYYYMMDD-HHMMSS`` inside a run name (local time), else None."""
    m = _RUN_TAIL.search(str(run))
    if not m:
        return None
    try:
        return datetime.strptime(f"{m['day']}-{m['hms']}", "%Y%m%d-%H%M%S").timestamp()
    except ValueError:
        return None


def _dossier_t(d: dict) -> float | None:
    """The dossier's ``t`` (local ISO, no zone) as an epoch; None when absent/unparsable."""
    t = d.get("t")
    if not t:
        return None
    try:
        return datetime.fromisoformat(str(t)).timestamp()
    except ValueError:
        return None


def _joins(run: str, agent_id: str, started: float | None) -> bool:
    """A run belongs to an agent when it ends in the agent's pid and (when ``started`` is known and the
    run name parses) it began no earlier than ``started - JOIN_SLACK_S``."""
    if run_pid(run) is None or run_pid(run) != run_pid(agent_id):
        return False
    if started is None:
        return True
    t0 = _run_started(run)
    return t0 is not None and t0 >= started - JOIN_SLACK_S


def classify(agent_id: str, started: float | None, dossiers: list[dict],
             anomalies: list[AnomalyRef], now: float) -> Health:
    """anomaly > stalled > slow > ok. An agent with no joined run data is ``ok``."""
    fresh = [a for a in anomalies
             if _joins(a.run, agent_id, started) and now - a.mtime <= ANOMALY_FRESH_S]
    if fresh:
        a = fresh[0]
        return Health(ANOMALY, (a.cause_hint or a.type)[:120], anomaly=a)
    joined = [(t, d) for d in dossiers if _joins(str(d.get("run") or ""), agent_id, started)
              and (t := _dossier_t(d)) is not None]
    if joined:
        t, d = max(joined, key=lambda td: td[0])
        age = now - t
        if age <= STALL_FRESH_S:
            cause = str(d.get("likely_cause") or "")
            why = str(d.get("reason") or "")
            return Health(STALLED, (f"{cause} - {why}" if why else cause)[:120],
                          dossier_run=str(d.get("run") or "") or None)
        if age <= STALL_SLOW_S:
            return Health(SLOW, f"stalled {int(age // 60)}min ago"[:120],
                          dossier_run=str(d.get("run") or "") or None)
    return Health(OK, "")
