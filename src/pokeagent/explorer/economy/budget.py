"""Budget: the reserve that is never spent. The Pokecenter is free, so money is only for supplies; the one real loss is a blackout,
which halves the money (Gen 1). The reserve is half of what the next blackout would cost, plus a floor that grows with bosses beaten."""
from __future__ import annotations

FLOOR, FLOOR_PER_BOSS = 300, 100
BOSS_GOALS = ("beat_brock", "beat_misty", "beat_surge", "beat_erika", "beat_koga", "beat_sabrina", "beat_blaine", "beat_giovanni")


def blackout_cost(money: int) -> int:
    return max(0, money) // 2


def reserve(goals: dict, money: int, ref_money: int = 0) -> int:
    """``ref_money``: the money at the start of the last Mart visit, so spending in one visit does not shrink the next one's reserve."""
    money = max(money, ref_money)
    return FLOOR + FLOOR_PER_BOSS * sum(1 for g in BOSS_GOALS if goals.get(g)) + blackout_cost(money) // 2


def spendable(goals: dict, money: int, ref_money: int = 0) -> int:
    return max(0, money - reserve(goals, money, ref_money))
