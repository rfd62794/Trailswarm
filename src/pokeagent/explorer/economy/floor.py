"""floor: the minimum Potion stock, and which Marts can fill it. Gen 1 has no repeatable money, so the policy is small on purpose:
the free Pokecenter heal is the default, and the bag holds only the few Potions (or Super Potions, 2.5 Potions each) the next stretch's expected HP loss needs
(never fewer than FLOOR_MIN, never more than FLOOR_CAP). A Mart is only worth the walk when it sells what the trip wants
(2026-11-07: the Vermilion Mart has no Potion, and 42 runs walked in, bought nothing useful and walked out; it does sell Super Potion)."""
from __future__ import annotations

import math

from pokeagent.explorer.economy import hp_stats
from pokeagent.explorer.economy import heal_items
from pokeagent.explorer.economy.prices import HEAL_HP, POTION, stocked

FLOOR_MIN, FLOOR_CAP = 1, 3


def potion_floor(stats, party, map_id, scale: float = 1.0) -> int:
    """Potions the next stretch needs: its expected HP loss over one Potion's heal, kept inside [FLOOR_MIN, FLOOR_CAP]."""
    need = math.ceil(scale * hp_stats.segment_loss(stats, party, map_id) / HEAL_HP[POTION])
    return max(FLOOR_MIN, min(FLOOR_CAP, need))


def floor_hp(target: int) -> int:
    """The floor in HP: ``target`` Potion-equivalents of 20 HP (a Super Potion counts 2.5)."""
    return target * heal_items.POTION_HP


def trip_is_floor(items, bag: dict) -> bool:
    """A bag with no heal item at all (Potion or Super Potion) is worth a trip for even one (a single one is under shopping.MIN_TRIP_YEN)."""
    return heal_items.heal_count(bag) <= 0 and any(i in HEAL_HP for i, _ in items)


def marts_selling(items, marts, stock=None) -> frozenset:
    """The Marts (of ``marts``) whose stock has at least one wanted item (any heal item stands in for another); unknown stock counts as selling."""
    ids, stock = {i for i, _ in items}, stock or stocked
    if ids & set(HEAL_HP):
        ids |= set(HEAL_HP)  # a heal trip is satisfied by any heal item (the Vermilion Mart sells Super Potion, not Potion)
    return frozenset(m for m in marts if any(stock(i, m) for i in ids))
