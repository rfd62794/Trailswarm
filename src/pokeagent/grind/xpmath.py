"""Gen 1 experience maths (pret/pokered): XP per kill and the cumulative-XP curves. Pure."""
from __future__ import annotations

TRAINER_XP = 1.5


def exp_for_level(growth: str, n: int) -> int:
    """Cumulative XP at level ``n`` for a growth group (the Gen 1 cubic formulas)."""
    if n <= 1:
        return 0
    g = growth.upper()
    if g == "MEDIUM_FAST":
        v = n ** 3
    elif g == "MEDIUM_SLOW":
        v = 6 * n ** 3 / 5 - 15 * n ** 2 + 100 * n - 140
    elif g == "FAST":
        v = 4 * n ** 3 / 5
    elif g == "SLOW":
        v = 5 * n ** 3 / 4
    else:
        raise ValueError(f"unknown growth group {growth!r}")
    return max(0, int(v))


def xp_gain(base_exp: int, enemy_level: int, trainer: bool = False, participants: int = 1) -> float:
    """XP each participant gets for a kill: base_exp * level / 7 (x1.5 for a trainer), split among participants."""
    return base_exp * enemy_level / 7 * (TRAINER_XP if trainer else 1.0) / max(1, participants)


def xp_needed(growth: str, level: int, target: int) -> int:
    """XP still to earn to go from the start of ``level`` to ``target`` (0 once there)."""
    return max(0, exp_for_level(growth, target) - exp_for_level(growth, level))
