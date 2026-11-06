"""Effect-aware move values: named multipliers over the base score (power x type x STAB x accuracy).

A table of constants, not rules, so the RL selector and the review tool can tune them. Every adjusted move gets a note
('drain', 'two-turn', 'catch-status') that move_scores appends to its rule string.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.knowledge.moves import effect_of, fixed_of

FIXED_SCALE = 3.5          # fixed damage -> power-equivalent (a 35-power hit does ~1/3.5 of its power in HP at battle levels)
CHARGE_DISCOUNT = 0.5      # SOLARBEAM / DIG / FLY: a wasted turn
RECHARGE_DISCOUNT = 0.5    # HYPER BEAM
RECOIL_DISCOUNT = 0.9
FAINT_DISCOUNT = 0.25      # SELFDESTRUCT / EXPLOSION: only when nothing else works
OHKO_VALUE = 35.0          # x accuracy (~30%)
DRAIN_LOW_HP, DRAIN_NORMAL = 1.25, 1.05
SIDE_EFFECT_BONUS = 0.5    # x chance, on top of the damage
CATCH_STATUS = {"sleep": 70.0, "paralyse": 55.0, "poison": 25.0, "confuse": 15.0}   # while catching, foe has no status
FIGHT_STATUS = {"sleep": 8.0, "paralyse": 6.0}      # in a normal fight: tiny, never beats a damaging move
STAT_DOWN_FIGHT = 4.0      # foe stat-down: low, and only in a fight that is not about to end
HEAL_VALUE, HEAL_BELOW = 40.0, 0.4
TRAP_BONUS = 1.1


@dataclass(frozen=True)
class ScoreCtx:
    level: int = 0
    hp_frac: float = 1.0
    enemy_hp: int = 0
    enemy_status: int = 0
    catching: bool = False
    fast_ko: bool = False      # a damaging move already ends the fight in <= 2 turns: status moves are worth nothing


def _status_value(e, c: ScoreCtx) -> tuple[float, str]:
    if c.enemy_status or c.fast_ko:
        return 0.0, "foe already has a status" if c.enemy_status else "fight ends by damage"
    if c.catching and e.status in CATCH_STATUS:
        return CATCH_STATUS[e.status], "catch-status"
    return FIGHT_STATUS.get(e.status, 0.0), ""


def adjust(move: dict, base: float, eff: float, acc: float, c: ScoreCtx) -> tuple[float, str]:
    """(score, note) for one move; a move with no known effect keeps its base score."""
    e = effect_of(move)
    if e is None or e.kind == "damage" and e.fixed == "" and not _special(e):
        return base, ""
    fixed = fixed_of(move)
    if fixed:
        dmg = {"level": c.level, "half": c.enemy_hp // 2, "20": 20, "40": 40}[fixed]
        return (dmg * FIXED_SCALE * acc if eff > 0 else 0.0), f"fixed {fixed}"
    if e.ohko:
        return OHKO_VALUE * acc, "ohko"
    if e.kind == "damage":
        s, note = base * e.hits, []
        if e.hits > 1: note.append(f"{e.hits:g} hits")
        for flag, mult, tag in ((e.charge, CHARGE_DISCOUNT, "two-turn"), (e.recharge, RECHARGE_DISCOUNT, "recharge"),
                                (e.recoil, RECOIL_DISCOUNT, "recoil"), (e.faints, FAINT_DISCOUNT, "faints"), (e.trap, TRAP_BONUS, "trap")):
            if flag: s *= mult; note.append(tag)
        if e.heal: s *= DRAIN_LOW_HP if c.hp_frac < 0.5 else DRAIN_NORMAL; note.append("drain")
        if e.chance and e.status: s *= 1 + SIDE_EFFECT_BONUS * e.chance; note.append(f"{e.status} chance")
        if move.get("name") == "DREAM EATER" and not c.enemy_status & 7: return 0.0, "foe awake"
        return s, ",".join(note)
    if e.kind == "status":
        return _status_value(e, c)
    if e.kind == "stat" and e.stages < 0:
        return (0.0, "fight ends by damage") if c.fast_ko or c.catching else (STAT_DOWN_FIGHT, "stat-down")
    if e.heal and c.hp_frac < HEAL_BELOW:
        return HEAL_VALUE, "heal"
    return 0.0, ""


def _special(e) -> bool:
    return bool(e.hits != 1 or e.charge or e.recharge or e.recoil or e.faints or e.heal or e.trap or e.chance or e.ohko)
