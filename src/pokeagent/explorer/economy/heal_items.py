"""heal_items: the one place that knows which items heal the party and by how much (ids checked against kb/items.json, built
from the ROM by knowledge/items_catalog: 0x14 POTION 300 yen, 0x13 SUPER POTION 700 yen; HP from prices.HEAL_HP). Policy is
minimal potions, but they stay an option: battle and field use take the smallest item that covers the missing HP, the floor
counts every heal item in HP-equivalent, and the shopping list buys the cheapest stocked item that fills the gap at the Mart
it is standing in."""
from __future__ import annotations

import math

from pokeagent.explorer.economy.prices import HEAL_HP, POTION, SUPER_POTION, price

HEAL_ITEMS = tuple(sorted(HEAL_HP, key=HEAL_HP.get))   # smallest heal first: (POTION, SUPER_POTION)
POTION_HP = HEAL_HP[POTION]                              # one "Potion-equivalent" = 20 HP


def heal_count(bag: dict) -> int:
    """Heal items carried (any kind)."""
    return sum(max(0, bag.get(i, 0)) for i in HEAL_ITEMS)


def bag_hp(bag: dict) -> int:
    """HP the carried heal items restore in total."""
    return sum(max(0, bag.get(i, 0)) * HEAL_HP[i] for i in HEAL_ITEMS)


def potion_equivalents(bag: dict) -> float:
    return bag_hp(bag) / POTION_HP


def pick_for_missing(bag: dict, missing: int, blocked=()) -> int | None:
    """The smallest carried heal item whose heal covers ``missing`` HP (a Super Potion is not wasted on 15 missing HP); when
    none covers it, the biggest carried one. None when the bag holds no usable heal item."""
    have = [i for i in HEAL_ITEMS if bag.get(i, 0) > 0 and i not in blocked]
    if not have:
        return None
    return next((i for i in have if HEAL_HP[i] >= missing), have[-1])


def buy_choice(need_hp: int, stock, afford: int):
    """``(item, qty)`` for the cheapest stocked heal item that fills ``need_hp`` within ``afford`` yen, or None.
    ``stock(item) -> bool``. Compared by total cost (ceil(need / heal) units); the smaller heal wins a tie. When no item fills
    the gap within ``afford``, it is the cheapest stocked item, as many as the money allows."""
    if need_hp <= 0:
        return None
    options = []
    for i in HEAL_ITEMS:
        unit = price(i)
        if unit and stock(i):
            n = math.ceil(need_hp / HEAL_HP[i])
            if n * unit <= afford:
                options.append((n * unit, HEAL_HP[i], i, n))
    if options:
        _, _, item, qty = min(options)
        return item, qty
    cheap = sorted((price(i), i) for i in HEAL_ITEMS if price(i) and stock(i) and price(i) <= afford)
    return (cheap[0][1], afford // cheap[0][0]) if cheap else None


__all__ = ["HEAL_ITEMS", "HEAL_HP", "POTION", "SUPER_POTION", "bag_hp", "buy_choice", "heal_count", "pick_for_missing", "potion_equivalents"]
