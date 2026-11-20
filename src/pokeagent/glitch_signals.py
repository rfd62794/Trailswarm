"""Read-only RAM probes for the Gen I glitch signatures our route can hit by accident.

An invalid per-map meta-map script byte, stuck trainer-bookkeeping flags or a movement-override byte persist
across leave/save/reset, so a checkpoint saved while one is active poisons every run that loads it
(docs/research/gen1-glitches-2026-11-15.md sections 2 rows 2/4/7/24, 3.1 and 5). These reads never write to the
emulator and never trigger anything: detectors log them and ``glitch_guard`` refuses checkpoint writes on the
verified ones. Addresses come from ``data/ram_map.json`` (pret/pokered ``pokered.sym``, "symbols branch").
Constants marked UNVERIFIED feed detectors only; the guard never enforces them.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.ram_symbols import IS_IN_BATTLE

VIRIDIAN_FOREST_SCRIPT = 0xD618   # wViridianForestCurScript (ram_map.json)
MISC_FLAGS = 0xCD60               # wMiscFlags (ram_map.json); bit 0 stuck = trainer bookkeeping (research row 2)
STATUS_FLAGS5 = 0xD730            # wStatusFlags5 (ram_map.json: "bit 7 = no joypad input / scripted walk"); bit 0 per research row 2
ENGAGED_TRAINER_CLASS = 0xCD2D    # wEngagedTrainerClass (ram_map.json)
ENGAGED_TRAINER_SET = 0xCD2E      # wEngagedTrainerSet (ram_map.json): aliases wEnemyMonStatMods, so read only outside battle
MISC_SEEN_BY_TRAINER = 0x01       # wMiscFlags BIT_SEEN_BY_TRAINER (pokered ram_constants.asm); set by TrainerEngage
MOVE_OVERRIDE = 0xCD3B            # wOverrideSimulatedJoypadStatesMask (ram_map.json); research row 7's movement override byte
TEXT_DELAY_D358 = 0xD358          # wLetterPrintingDelayFlags (ram_map.json; ram_findings.json: bit 1 clears on menu_open)
INSTANT_TEXT_CANDIDATE = 0x40     # UNVERIFIED: wStatusFlags5 bit 6 (ram_findings.json: sets on menu_open); whether the
                                # Cerulean Bike Shop trick leaves it set is not established
VIRIDIAN_FOREST_SCRIPT_MAX = 2    # UNVERIFIED ceiling, doc-backed (research row 4, "Meta-map script activation"): values
                                # 3, 4, ... are out of range for trainer-only maps; 06 is the Forest signature


@dataclass(frozen=True)
class Signals:
    """The glitch-relevant RAM bytes at one instant. ``engaged_*`` read 0 inside a battle (their address is
    reused by battle stat mods), so the rules below treat them as stale only outside battle."""

    forest_script: int = 0
    misc_flags: int = 0
    status5: int = 0
    engaged_class: int = 0
    engaged_set: int = 0
    move_override: int = 0
    in_battle: bool = False
    text_d358: int = 0

    def as_tuple(self) -> tuple:
        """The fields in declaration order (Snapshot.sig carries this; bools stay bools)."""
        return (self.forest_script, self.misc_flags, self.status5, self.engaged_class, self.engaged_set,
                self.move_override, self.in_battle, self.text_d358)

    @classmethod
    def from_tuple(cls, t) -> "Signals | None":
        """Inverse of ``as_tuple``; ``()``/None (a snapshot taken before signals existed) reads as None."""
        if not t:
            return None
        t = tuple(t)
        return cls(*((t + (0,) * len(cls.__dataclass_fields__))[:len(cls.__dataclass_fields__)]))


def read_signals(emu) -> Signals:
    """One byte per signal. ``engaged_*`` is read only outside battle: 0xCD2E aliases wEnemyMonStatMods."""
    in_battle = bool(emu.read(IS_IN_BATTLE))
    return Signals(forest_script=emu.read(VIRIDIAN_FOREST_SCRIPT), misc_flags=emu.read(MISC_FLAGS),
                   status5=emu.read(STATUS_FLAGS5),
                   engaged_class=0 if in_battle else emu.read(ENGAGED_TRAINER_CLASS),
                   engaged_set=0 if in_battle else emu.read(ENGAGED_TRAINER_SET),
                   move_override=emu.read(MOVE_OVERRIDE), in_battle=in_battle,
                   text_d358=emu.read(TEXT_DELAY_D358))


def active_reasons(sig: Signals) -> list[str]:
    """Stable reason names for every signature that is verifiably wrong right now (each a pure rule)."""
    out = []
    if sig.forest_script > VIRIDIAN_FOREST_SCRIPT_MAX:   # checked regardless of the current map: the byte persists
        out.append("script_oor")
    if not sig.in_battle:
        if (sig.misc_flags & 1 or sig.status5 & 1) and sig.engaged_class == 0 and sig.engaged_set == 0:
            out.append("trainer_flags_stuck")
        if sig.move_override != 0:
            out.append("move_override")
    return out


def instant_text_candidate(sig: Signals) -> bool:
    """UNVERIFIED instant-text signature (wStatusFlags5 bit 6): logged by a detector only, never an active reason."""
    return bool(sig.status5 & INSTANT_TEXT_CANDIDATE)


def engaged_now(sig: Signals) -> bool:
    """True while a trainer has spotted the player outside battle: wMiscFlags BIT_SEEN_BY_TRAINER is set.

    NEVER reads ``engaged_class`` / ``engaged_set``: wEngagedTrainerClass is written only by EngageMapTrainer and
    never cleared, so it is a stale last-engaged byte that reads nonzero with no trainer engaged (real-ROM
    2026-11-19: 21, 14, 230). This function cannot tell "engaged" from "bit stuck at 1"; ``engagement_edge`` can.
    """
    return not sig.in_battle and bool(sig.misc_flags & MISC_SEEN_BY_TRAINER)


def engagement_edge(prev: Signals, cur: Signals) -> str | None:
    """``"seen"`` on a 0 -> 1 edge of BIT_SEEN_BY_TRAINER outside battle, ``"battle"`` when a battle starts
    (``in_battle`` is a bool, so wild and trainer are not told apart), else None. A bit stuck at 1 on both
    samples yields None: unlike ``engaged_now``, an edge separates a fresh engagement from a stuck flag."""
    if not prev.misc_flags & MISC_SEEN_BY_TRAINER and cur.misc_flags & MISC_SEEN_BY_TRAINER and not cur.in_battle:
        return "seen"
    if not prev.in_battle and cur.in_battle:
        return "battle"
    return None
