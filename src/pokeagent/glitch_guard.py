"""Checkpoint write guard: refuse to persist a state while a route-reachable glitch signature is active.

An invalid per-map script byte or stuck trainer flags saved into a curriculum checkpoint or leg state poisons
every run that loads it (docs/research/gen1-glitches-2026-11-15.md sections 3.1 and 5). The guard READS RAM
only: it never writes SRAM or save data, and a refusal is itself recorded as a ``checkpoint_refused`` discovery
through ``DiscoveryLog`` - its save state lands in the discovery-state directory no checkpoint code reads. It
never raises: an internal error returns True, so a guard bug cannot block a healthy run.
"""
from __future__ import annotations

from pokeagent.glitch_signals import active_reasons, read_signals
from pokeagent.statefp import MAP, X, Y


def allow_write(emu, what, *, runs_dir="runs", run="", log=None) -> bool:
    """True when RAM shows no active glitch signature; False while one is, logging the refused write.

    ``what`` names the write (``goal:<name>``, ``team_best``, ``end_state``, ``leg:<m>_<x>_<y>``,
    ``trainee:<stem>``). On refusal the caller skips the write and keeps the last clean state untouched."""
    try:
        sig = read_signals(emu)
        reasons = active_reasons(sig)
        if not reasons:
            return True
        from pokeagent.novelty.discoveries import DiscoveryLog
        from pokeagent.novelty.features import Snapshot
        raw = {"forest_script": sig.forest_script, "misc_flags": sig.misc_flags, "status5": sig.status5,
               "engaged_class": sig.engaged_class, "engaged_set": sig.engaged_set,
               "move_override": sig.move_override, "in_battle": sig.in_battle, "text_d358": sig.text_d358}
        DiscoveryLog(runs_dir, run, "guard").record("checkpoint_refused", "+".join(reasons), None,
                                                  {"what": what, **raw}, 0, emu,
                                                  Snapshot(map=emu.read(MAP), x=emu.read(X), y=emu.read(Y)))
        if log is not None:
            log(f"[checkpoint refused: {what}: {'+'.join(reasons)}]")
        return False
    except Exception:  # noqa: BLE001  a guard bug must never block a healthy run
        return True
