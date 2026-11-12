"""Budget: the reserve that is never spent. The Pokecenter is free, so money is only for supplies; the one real loss is a blackout,
which halves the money (Gen 1). The reserve is half of what the next blackout would cost, plus a floor that grows with bosses beaten."""
from __future__ import annotations

FLOOR, FLOOR_PER_BOSS = 300, 100
BOSS_GOALS = ("beat_brock", "beat_misty", "beat_surge", "beat_erika", "beat_koga", "beat_sabrina", "beat_blaine", "beat_giovanni")
_magikarp_floor = 0   # this step's extra reserve for the 500-yen Magikarp (explorer.magikarp_deferral.tick sets it)


def set_magikarp_floor(n: int) -> None:
    """Replace the Magikarp reserve floor (0 clears it). Same shape as training.set_blackout_tax: every
    reserve/spendable caller - shopping_list, candidate_bundles, restock._visit, catch_plan - sees it
    with no signature change."""
    global _magikarp_floor
    _magikarp_floor = n


def magikarp_floor() -> int:
    return _magikarp_floor


def blackout_cost(money: int) -> int:
    return max(0, money) // 2


def reserve(goals: dict, money: int, ref_money: int = 0) -> int:
    """``ref_money``: the money at the start of the last Mart visit, so spending in one visit does not shrink the next one's reserve."""
    money = max(money, ref_money)
    return max(FLOOR + FLOOR_PER_BOSS * sum(1 for g in BOSS_GOALS if goals.get(g)) + blackout_cost(money) // 2,
               _magikarp_floor)


def spendable(goals: dict, money: int, ref_money: int = 0) -> int:
    return max(0, money - reserve(goals, money, ref_money))
