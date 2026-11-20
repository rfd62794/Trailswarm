"""Checkpoint write guard: refuse to persist a state while a route-reachable glitch signature is active.

An invalid per-map script byte or stuck trainer flags saved into a curriculum checkpoint or leg state poisons
every run that loads it (docs/research/gen1-glitches-2026-11-15.md sections 3.1 and 5). The guard READS RAM
only: it never writes SRAM or save data, and a refusal is itself recorded as a ``checkpoint_refused`` discovery
through ``DiscoveryLog`` - its save state lands in the discovery-state directory no checkpoint code reads. It
never raises: an internal error returns True, so a guard bug cannot block a healthy run.
"""
from __future__ import annotations

from pathlib import Path
from weakref import WeakKeyDictionary

from pokeagent.glitch_signals import active_reasons, read_signals
from pokeagent.statefp import MAP, X, Y

# One DiscoveryLog per (runs_dir, run): its done-set dedupes identical refusals and MAX_PER_RUN caps a run's
# records across every call site, not just inside a single allow_write call.
_LOGS: dict = {}


def _log_for(runs_dir, run):
    from pokeagent.novelty.discoveries import DiscoveryLog
    return _LOGS.setdefault((str(Path(runs_dir)), run), DiscoveryLog(runs_dir, run, "guard"))


# Per-emulator persistence counters, independent of --novelty: the engine feeds them every press via ``observe``
# (allow_write feeds them itself only on an emulator no hook has ever fed, e.g. a bare script or test).
_STREAKS: WeakKeyDictionary = WeakKeyDictionary()
_PERSISTENT = ("trainer_flags_stuck", "move_override")   # scripted walks blip these; script_oor stays instant


class _Streak:
    def __init__(self):
        self.counts = {r: 0 for r in _PERSISTENT}
        self.hooked = False


def _state(emu):
    try:
        st = _STREAKS.get(emu)
        if st is None:
            st = _STREAKS[emu] = _Streak()
        return st
    except TypeError:   # not weak-referenceable: no streak can build, so the persistent reasons never refuse
        return _Streak()


def _count(emu, reasons) -> dict:
    st = _state(emu)
    for r in _PERSISTENT:
        st.counts[r] = st.counts[r] + 1 if r in reasons else 0
    return st.counts


def observe(emu) -> None:
    """Per-press hook: feed the streak counters from one RAM read. Never raises."""
    try:
        _state(emu).hooked = True
        _count(emu, active_reasons(read_signals(emu)))
    except Exception:  # noqa: BLE001
        pass


def allow_write(emu, what, *, runs_dir="runs", run="", log=None) -> bool:
    """True when RAM shows no active glitch signature; False while one is, logging the refused write.

    ``what`` names the write (``goal:<name>``, ``team_best``, ``end_state``, ``leg:<m>_<x>_<y>``,
    ``trainee:<stem>``). On refusal the caller skips the write and keeps the last clean state untouched."""
    try:
        sig = read_signals(emu)
        from pokeagent.novelty.discoveries import STUCK_STEPS
        active = active_reasons(sig)
        counts = _state(emu).counts if _state(emu).hooked else _count(emu, active)
        # trainer_flags_stuck / move_override blip during scripted walks: refuse only after STUCK_STEPS consecutive
        # observations. script_oor stays instantaneous (the byte persists).
        reasons = [r for r in active if r not in _PERSISTENT or counts[r] >= STUCK_STEPS]
        if not reasons:
            return True
        from pokeagent.novelty.features import Snapshot
        raw = {"forest_script": sig.forest_script, "misc_flags": sig.misc_flags, "status5": sig.status5,
               "engaged_class": sig.engaged_class, "engaged_set": sig.engaged_set,
               "move_override": sig.move_override, "in_battle": sig.in_battle, "text_d358": sig.text_d358}
        dlog = _log_for(runs_dir, run)
        # len(records) stands in for the step: it keeps each refusal's .discovery.state filename distinct
        # (a fixed step would write every kind to <run>-<step>-checkpoint_refused.discovery.state).
        dlog.record("checkpoint_refused", "+".join(reasons), None, {"what": what, **raw},
                    len(dlog.records), emu, Snapshot(map=emu.read(MAP), x=emu.read(X), y=emu.read(Y)))
        if log is not None:
            log(f"[checkpoint refused: {what}: {'+'.join(reasons)}]")
        return False
    except Exception:  # noqa: BLE001  a guard bug must never block a healthy run
        return True
