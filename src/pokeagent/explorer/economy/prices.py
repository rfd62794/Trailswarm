"""Item ids and prices. Prices come from the ROM table when it is there (kb/rom_tables.json is gitignored); the fallbacks are
the well-known Gen 1 Mart prices so the rules still work on a machine without the ROM."""
from __future__ import annotations

from pokeagent.explorer.kb import ROM_KB
from pokeagent.knowledge import items_catalog

POKE_BALL, ANTIDOTE, PARLYZ_HEAL, SUPER_POTION, POTION = 0x04, 0x0B, 0x0F, 0x13, 0x14
ESCAPE_ROPE, REPEL, NUGGET = 0x1D, 0x1E, 0x31
FALLBACK_PRICE = {POKE_BALL: 200, ANTIDOTE: 100, PARLYZ_HEAL: 200, SUPER_POTION: 700, POTION: 300, ESCAPE_ROPE: 550, REPEL: 350, NUGGET: 10000}
HEAL_HP = {POTION: 20, SUPER_POTION: 50}
SELL_DIVISOR = 2                      # a Mart pays half the buy price
SELL_WHITELIST = frozenset({NUGGET})  # the only item the agent may ever sell


def sell_allowed(item_id: int) -> bool:
    """Whitelisted AND not a key item (the whitelist alone is one edit away from selling a BICYCLE; item_policies.key_items is the shield)."""
    from pokeagent.explorer.item_policies.key_items import is_key_item
    return item_id in SELL_WHITELIST and not is_key_item(item_id)


def price(item_id: int) -> int:
    """Catalog (kb/items.json, built from the ROM) > ROM table > the fallbacks above."""
    cat = items_catalog.load()
    row = items_catalog.item(cat, item_id) if cat else None
    if row and row["price"]:
        return row["price"]
    rom = ((ROM_KB or {}).get("items", {}).get(str(item_id), {}) or {}).get("price")
    return int(rom or FALLBACK_PRICE.get(item_id, 0))


def stocked(item_id: int, map_id: int) -> bool:
    """Does the Mart on ``map_id`` sell the item? True when the catalog has no stock list for it (unknown = try)."""
    cat = items_catalog.load()
    stock = items_catalog.stock_for_map(cat, map_id) if cat else None
    return stock is None or item_id in stock


def sell_price(item_id: int) -> int:
    return price(item_id) // SELL_DIVISOR
