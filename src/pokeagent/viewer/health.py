"""Stall/break health for the viewer: classify agents from run files, hold the last snapshot.

Read-only diagnosis surfaced in the UI: stall dossiers (``runs/stalls/*.json`` via
``stalls.load_dossiers``), anomaly captures (``runs/anomalies/*.png|.state`` + ``anomalies.jsonl``)
and invariant findings (``invariants.runner.run_all``). The poll thread calls ``refresh`` at <= 1 Hz;
the render path only does dict lookups on the last snapshot. Pure except the readers.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pokeagent.invariants.findings import ERROR, WARN
from pokeagent.invariants.runner import run_all
from pokeagent.stalls import load_dossiers

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


def anomalies_for(root: Path) -> list[AnomalyRef]:
    """``runs/anomalies/<run>-<step>-<type>.png|.state`` pairs, newest first; tolerant of junk names
    and a missing dir. ``anomalies.jsonl`` is read only for ``cause_hint``/``provenance``."""
    adir = Path(root) / "runs" / "anomalies"
    try:
        files = list(adir.iterdir())
    except OSError:
        return []
    hints: dict[tuple[str, int], tuple[str, str]] = {}
    try:
        with open(Path(root) / "runs" / "anomalies.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("run") is not None:
                    hints[(str(row["run"]), row.get("step"))] = (
                        str(row.get("cause_hint") or ""), str(row.get("provenance") or ""))
    except OSError:
        pass
    parts: dict[str, dict[str, Path]] = {}
    for p in files:
        if p.suffix not in (".png", ".state"):
            continue
        bits = p.stem.rsplit("-", 2)
        if len(bits) < 3 or not bits[1].isdigit():
            continue
        parts.setdefault(p.stem, {})[p.suffix] = p
    out: list[AnomalyRef] = []
    for stem, pair in parts.items():
        run, step_s, atype = stem.rsplit("-", 2)
        try:
            mtime = max(p.stat().st_mtime for p in pair.values())
        except OSError:
            mtime = 0.0
        hint, prov = hints.get((run, int(step_s)), ("", ""))
        out.append(AnomalyRef(run=run, step=int(step_s), type=atype,
                              png=pair.get(".png"), state=pair.get(".state"),
                              mtime=mtime, cause_hint=hint, provenance=prov))
    return sorted(out, key=lambda a: a.mtime, reverse=True)


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


def break_summary(findings: list) -> dict:
    """``{"errors": n, "warns": n, "top": [first 3 ERROR messages]}``."""
    errors = [f for f in findings if getattr(f, "level", None) == ERROR]
    warns = [f for f in findings if getattr(f, "level", None) == WARN]
    return {"errors": len(errors), "warns": len(warns),
            "top": [getattr(f, "message", str(f)) for f in errors[:3]]}


def poll_due(tick: int, fps: int, poll_s: float = HEALTH_POLL_S) -> bool:
    """The 1 Hz heartbeat inside ``poller()``: true once per ``fps * poll_s`` ticks."""
    return tick % max(1, round(fps * poll_s)) == 0


def badge_text(counts: dict[str, int], breaks: dict | None) -> str:
    """``Health: 1 stalled, 1 anomaly | invariants: 0 errors`` (checking... / unavailable variants)."""
    seg = [f"{counts.get(STALLED, 0)} stalled"]
    if counts.get(ANOMALY):
        seg.append(f"{counts[ANOMALY]} anomaly")
    if counts.get(SLOW):
        seg.append(f"{counts[SLOW]} slow")
    if breaks is None:
        inv = "checking..."
    elif "unavailable" in breaks:
        inv = "unavailable"
    else:
        inv = f"{breaks.get('errors', 0)} errors"
    return f"Health: {', '.join(seg)} | invariants: {inv}"


def worst_state(states: list[str]) -> str:
    """The worst health state in the list (drives the badge colour)."""
    for s in (ANOMALY, STALLED, SLOW):
        if s in states:
            return s
    return OK


class HealthStore:
    """Last health snapshot; refreshed on the poll thread, read (dict lookups) on the render thread."""

    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._dossiers: list[dict] = []
        self._anomalies: list[AnomalyRef] = []
        self._prov: dict[str, str] = {}
        self._mtimes: dict[str, float | None] = {}
        self._breaks: dict | None = None         # None until the first invariant result ("checking...")
        self._inv_last = 0.0
        self._inv_running = False
        self._fakes: dict[str, Health] = {}

    # -- writes (poll thread only) ---------------------------------------------------
    def _paths(self, root: Path) -> dict[str, Path]:
        r = Path(root) / "runs"
        return {"stalls": r / "stalls", "anomalies": r / "anomalies", "jsonl": r / "anomalies.jsonl"}

    def _stat(self, p: Path) -> float | None:
        try:
            return p.stat().st_mtime
        except OSError:
            return None

    def refresh(self, root: Path, now: float) -> None:
        """Stat the watched paths first; re-read only what changed. Never raises."""
        try:
            mt = {k: self._stat(p) for k, p in self._paths(root).items()}
            dossiers = anomalies = None
            with self._lock:
                old = dict(self._mtimes)
                self._mtimes = mt
            if mt["stalls"] is not None and mt["stalls"] != old.get("stalls"):
                dossiers = load_dossiers(root)
            if (mt["anomalies"] is not None and mt["anomalies"] != old.get("anomalies")) or \
               (mt["jsonl"] is not None and mt["jsonl"] != old.get("jsonl")):
                anomalies = anomalies_for(root)
            with self._lock:
                if dossiers is not None:
                    self._dossiers = dossiers
                    self._prov.update({str(d.get("run")): str(d.get("provenance") or "")
                                       for d in dossiers if d.get("run")})
                if anomalies is not None:
                    self._anomalies = anomalies
        except Exception:
            pass

    def fake_refresh(self, agent_ids: list[str], now: float) -> None:
        """``--fake`` path: one stalled and one anomaly card so the colours show without run data."""
        fakes: dict[str, Health] = {}
        for i, aid in enumerate(sorted(agent_ids)):
            if i == 0:
                fakes[aid] = Health(STALLED, "fake stall (demo) - no new tiles in 600 presses",
                                    dossier_run=None)
            elif i == 1:
                fakes[aid] = Health(ANOMALY, "fake anomaly (demo)",
                                    anomaly=AnomalyRef(run=aid, step=0, type="endless_battle",
                                                       png=None, state=None, mtime=now,
                                                       cause_hint="fake anomaly (demo)"))
            else:
                fakes[aid] = Health(OK, "")
        with self._lock:
            self._fakes = fakes

    def request_invariants(self, root: Path, now: float) -> None:
        """At most one daemon worker; a failure stores ``{"unavailable": message}``."""
        with self._lock:
            if self._inv_running or now - self._inv_last < INVARIANT_EVERY_S:
                return
            self._inv_running, self._inv_last = True, now

        def work() -> None:
            try:
                out: dict = break_summary(run_all(Path(root) / "runs"))
            except Exception as exc:
                out = {"unavailable": str(exc)}
            with self._lock:
                self._breaks, self._inv_running = out, False

        threading.Thread(target=work, daemon=True, name="health-invariants").start()

    # -- reads (render thread; dict lookups only, never file I/O) ---------------------
    def health(self, agent_id: str, started: float | None) -> Health:
        with self._lock:
            fake = self._fakes.get(agent_id)
            dossiers, anomalies = list(self._dossiers), list(self._anomalies)
        if fake is not None:
            return fake
        return classify(agent_id, started, dossiers, anomalies, self._clock())

    def breaks(self) -> dict | None:
        with self._lock:
            return dict(self._breaks) if self._breaks is not None else None

    def anomalies(self, limit: int = 10) -> list[AnomalyRef]:
        with self._lock:
            return list(self._anomalies[:limit])

    def provenance(self, run: str | None) -> str:
        with self._lock:
            return self._prov.get(run or "", "")
