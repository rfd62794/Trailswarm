"""Gen 1 damage estimate: the cartridge formula with the average random roll and no critical, for matchup maths."""
from __future__ import annotations

import math

PHYSICAL = {"NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BUG", "GHOST"}  # the rest are special
AVG_ROLL = 0.925          # random factor is 217..255 / 255
CRIT_RATE = 0.06          # fold crits in as a small average bonus (they ignore stages, roughly double)
HIT_FLOOR = 1


def type_mult(chart: dict, move_type: str, def_types: list[str]) -> float:
    """Chart multiplier of move_type vs each (distinct) defender type, multiplied."""
    eff = 1.0
    for t in dict.fromkeys(def_types):
        eff *= chart.get((move_type, t), 1.0)
    return eff


def expected_damage(level: int, power: int, atk: int, dfn: int, *, stab: bool, eff: float) -> float:
    """Average damage of one use: floor(floor(floor(2L/5+2)*P*A/D)/50)+2, x1.5 STAB, x type, x average roll."""
    if power <= 1 or atk <= 0 or dfn <= 0 or eff <= 0:
        return 0.0
    base = (((2 * level // 5 + 2) * power * atk // dfn) // 50) + 2
    dmg = base * (1.5 if stab else 1.0) * eff * AVG_ROLL * (1 + CRIT_RATE)
    return max(dmg, HIT_FLOOR)


def turns_to_ko(hp: int, dmg_per_turn: float) -> float:
    """Turns to remove hp at dmg_per_turn (inf when it cannot)."""
    return math.inf if dmg_per_turn <= 0 else max(1.0, math.ceil(hp / dmg_per_turn))
