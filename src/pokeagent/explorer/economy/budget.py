"""Budget: the reserve that is never spent. The Pokecenter is free, so money is only for supplies; the one real loss is a blackout,
which halves the money (Gen 1). The reserve is half of what the next blackout would cost, plus a floor that grows with bosses beaten."""
from __future__ import annotations

FLOOR, FLOOR_PER_BOSS = 300, 100
BOSS_GOALS = ("beat_brock", "beat_misty", "beat_surge", "beat_erika", "beat_koga", "beat_sabrina", "beat_blaine", "beat_giovanni")


def blackout_cost(money: int) -> int:
    return max(0, money) // 2


def reserve(goals: dict, money: int) -> int:
    return FLOOR + FLOOR_PER_BOSS * sum(1 for g in BOSS_GOALS if goals.get(g)) + blackout_cost(money) // 2


def spendable(goals: dict, money: int) -> int:
    return max(0, money - reserve(goals, money))
