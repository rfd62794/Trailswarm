"""Stall/break health for the viewer: classify agents from run files, hold the last snapshot.

Read-only diagnosis surfaced in the UI: stall dossiers (``runs/stalls/*.json`` via
``stalls.load_dossiers``), anomaly captures (``runs/anomalies/*.png|.state`` + ``anomalies.jsonl``)
and invariant findings (``invariants.runner.run_all``). The poll thread calls ``refresh`` at <= 1 Hz;
the render path only does dict lookups on the last snapshot. Pure except the readers.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path

from pokeagent.invariants.findings import ERROR, WARN
from pokeagent.invariants.runner import run_all
from pokeagent.stalls import load_dossiers
from pokeagent.viewer.health_classify import (  # noqa: F401  (re-exported: the public health API)
    ANOMALY, ANOMALY_FRESH_S, HEALTH_POLL_S, INVARIANT_EVERY_S, JOIN_SLACK_S, OK, SLOW, STALL_FRESH_S,
    STALL_SLOW_S, STALLED, AnomalyRef, Health, _dossier_t, _joins, _run_started, classify, run_pid)

log = logging.getLogger(__name__)


def started_map(entries: dict) -> dict[str, float | None]:
    """``{agent_id: started epoch or None}`` from the registry entries (computed once per refresh)."""
    out: dict[str, float | None] = {}
    for aid, e in entries.items():
        try:
            out[aid] = float(e["started"]) if isinstance(e, dict) and e.get("started") is not None else None
        except (TypeError, ValueError):
            out[aid] = None
    return out


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


def break_summary(findings: list) -> dict:
    """``{"errors": n, "warns": n, "top": [first 3 ERROR messages]}``."""
    errors = [f for f in findings if getattr(f, "level", None) == ERROR]
    warns = [f for f in findings if getattr(f, "level", None) == WARN]
    return {"errors": len(errors), "warns": len(warns),
            "top": [getattr(f, "message", str(f)) for f in errors[:3]]}


def poll_due(tick: int, fps: int, poll_s: float = HEALTH_POLL_S) -> bool:
    """The 1 Hz heartbeat inside ``poller()``: true once per ``fps * poll_s`` ticks."""
    return tick % max(1, round(fps * poll_s)) == 0


def badge_text(counts: dict[str, int], breaks: dict | None, error: str | None = None) -> str:
    """``Health: 1 stalled, 1 anomaly | invariants: 0 errors`` (checking... / unavailable variants);
    ``| read error`` is appended while the last run-file read failed."""
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
    return f"Health: {', '.join(seg)} | invariants: {inv}" + (" | read error" if error else "")


def worst_state(states: list[str]) -> str:
    """The worst health state in the list (drives the badge colour)."""
    for s in (ANOMALY, STALLED, SLOW):
        if s in states:
            return s
    return OK


_OK_HEALTH = Health(OK, "")


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
        self._agents: dict[str, float | None] = {}   # agent_id -> registry ``started`` epoch (the join key)
        self._health: dict[str, Health] = {}         # classified once per refresh; health() only looks up
        self._logged: set[str] = set()               # failure messages already logged (once per failure)
        self._errors: list[str] = []
        self.last_error: str | None = None           # last run-file read failure; None after a clean refresh

    # -- writes (poll thread only) ---------------------------------------------------
    def _paths(self, root: Path) -> dict[str, Path]:
        r = Path(root) / "runs"
        return {"stalls": r / "stalls", "anomalies": r / "anomalies", "jsonl": r / "anomalies.jsonl"}

    def _stat(self, p: Path) -> float | None:
        try:
            return p.stat().st_mtime
        except OSError:
            return None

    def _read(self, name: str, fn, root: Path):
        """Run one reader. On failure: log once, set ``last_error``, return ``(False, None)``."""
        try:
            out = fn(root)
        except Exception as exc:
            msg = f"{name}: {type(exc).__name__}: {exc}"
            if msg not in self._logged:
                self._logged.add(msg)
                log.warning("health read failed (%s); will retry next refresh", msg)
            self._errors.append(msg)
            return False, None
        return True, out

    def refresh(self, root: Path, now: float, agents: dict[str, float | None] | None = None) -> None:
        """Stat the watched paths first; re-read only what changed, then classify every agent once.

        A path's mtime is recorded only after its read succeeded, so a failed read is retried next
        refresh. ``agents`` maps agent_id -> started epoch (kept from the previous call when omitted).
        Never raises."""
        self._errors: list[str] = []
        try:
            mt = {k: self._stat(p) for k, p in self._paths(root).items()}
            with self._lock:
                old = dict(self._mtimes)
            done: dict[str, float | None] = {}
            dossiers = anomalies = None
            for k in mt:
                if mt[k] is None:
                    done[k] = None          # absent: nothing to read; reappearing counts as a change
            if mt["stalls"] is not None and mt["stalls"] != old.get("stalls"):
                ok, dossiers = self._read("dossiers", load_dossiers, root)
                if ok:
                    done["stalls"] = mt["stalls"]
            elif mt["stalls"] is not None:
                done["stalls"] = mt["stalls"]
            anomalies_changed = mt["anomalies"] is not None and mt["anomalies"] != old.get("anomalies")
            jsonl_changed = mt["jsonl"] is not None and mt["jsonl"] != old.get("jsonl")
            if anomalies_changed or jsonl_changed:
                ok, anomalies = self._read("anomalies", anomalies_for, root)
                if ok:
                    done["anomalies"], done["jsonl"] = mt["anomalies"], mt["jsonl"]
            else:
                done["anomalies"], done["jsonl"] = mt["anomalies"], mt["jsonl"]
            with self._lock:
                self._mtimes = {**old, **done}
                if dossiers is not None:
                    self._dossiers = dossiers
                    self._prov.update({str(d.get("run")): str(d.get("provenance") or "")
                                       for d in dossiers if d.get("run")})
                if anomalies is not None:
                    self._anomalies = anomalies
                if agents is not None:
                    self._agents = dict(agents)
                self._health = {aid: classify(aid, st, self._dossiers, self._anomalies, now)
                                for aid, st in self._agents.items()}
        except Exception as exc:
            self._errors.append(f"refresh: {type(exc).__name__}: {exc}")
            msg = self._errors[-1]
            if msg not in self._logged:
                self._logged.add(msg)
                log.warning("health refresh failed (%s)", msg)
        with self._lock:
            self.last_error = "; ".join(self._errors) or None
        if not self._errors:
            self._logged.clear()            # recovered: a later failure logs again

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
    def health(self, agent_id: str, started: float | None = None) -> Health:
        """The agent's health from the last refresh (``started`` is unused: refresh holds it).
        An agent not yet seen by a refresh is ``ok``."""
        with self._lock:
            return self._fakes.get(agent_id) or self._health.get(agent_id) or _OK_HEALTH

    def breaks(self) -> dict | None:
        with self._lock:
            return dict(self._breaks) if self._breaks is not None else None

    def anomalies(self, limit: int = 10) -> list[AnomalyRef]:
        with self._lock:
            return list(self._anomalies[:limit])

    def provenance(self, run: str | None) -> str:
        with self._lock:
            return self._prov.get(run or "", "")


# -- map marker ring (world view): the agent's colour while healthy, the health colour when not -------------------
RING_COLOUR = {SLOW: (255, 200, 80), STALLED: (255, 60, 60), ANOMALY: (255, 80, 255)}
PULSE_HZ = 1.5


def ring_colour(state: str, agent_colour: tuple[int, int, int]) -> tuple[int, int, int]:
    return RING_COLOUR.get(state, agent_colour)


def ring_alpha(state: str, now: float) -> int:
    """255, except a stalled agent's ring pulses between 70 and 255 so it catches the eye."""
    if state != STALLED:
        return 255
    return int(162 + 93 * math.sin(now * 2 * math.pi * PULSE_HZ))
