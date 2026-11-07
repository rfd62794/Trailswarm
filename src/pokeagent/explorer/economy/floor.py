"""floor: the minimum Potion stock, and which Marts can fill it. Gen 1 has no repeatable money, so the policy is small on purpose:
the free Pokecenter heal is the default, and the bag holds only the few Potions the next stretch's expected HP loss needs
(never fewer than FLOOR_MIN, never more than FLOOR_CAP). A Mart is only worth the walk when it sells what the trip wants
(2026-11-07: the Vermilion Mart has no Potion, and 42 runs walked in, bought nothing useful and walked out)."""
from __future__ import annotations

import math

from pokeagent.explorer.economy import hp_stats
from pokeagent.explorer.economy.prices import HEAL_HP, POTION, stocked

FLOOR_MIN, FLOOR_CAP = 1, 3


def potion_floor(stats, party, map_id, scale: float = 1.0) -> int:
    """Potions the next stretch needs: its expected HP loss over one Potion's heal, kept inside [FLOOR_MIN, FLOOR_CAP]."""
    need = math.ceil(scale * hp_stats.segment_loss(stats, party, map_id) / HEAL_HP[POTION])
    return max(FLOOR_MIN, min(FLOOR_CAP, need))


def trip_is_floor(items, bag: dict) -> bool:
    """A bag with no Potion at all is worth a trip for even one (a single Potion is under shopping.MIN_TRIP_YEN)."""
    return bag.get(POTION, 0) <= 0 and any(i == POTION for i, _ in items)


def marts_selling(items, marts, stock=None) -> frozenset:
    """The Marts (of ``marts``) whose stock has at least one wanted item; unknown stock counts as selling."""
    ids, stock = {i for i, _ in items}, stock or stocked
    return frozenset(m for m in marts if any(stock(i, m) for i in ids))
