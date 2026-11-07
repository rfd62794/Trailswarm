"""Item ids and prices. Prices come from the ROM table when it is there (kb/rom_tables.json is gitignored); the fallbacks are
the well-known Gen 1 Mart prices so the rules still work on a machine without the ROM."""
from __future__ import annotations

from pokeagent.explorer.kb import ROM_KB

POKE_BALL, ANTIDOTE, PARLYZ_HEAL, SUPER_POTION, POTION = 0x04, 0x0B, 0x0F, 0x13, 0x14
ESCAPE_ROPE, REPEL, NUGGET = 0x1D, 0x1E, 0x31
FALLBACK_PRICE = {POKE_BALL: 200, ANTIDOTE: 100, PARLYZ_HEAL: 200, SUPER_POTION: 700, POTION: 300, ESCAPE_ROPE: 550, REPEL: 350, NUGGET: 10000}
HEAL_HP = {POTION: 20, SUPER_POTION: 50}
SELL_DIVISOR = 2                      # a Mart pays half the buy price
SELL_WHITELIST = frozenset({NUGGET})  # the only item the agent may ever sell


def price(item_id: int) -> int:
    rom = ((ROM_KB or {}).get("items", {}).get(str(item_id), {}) or {}).get("price")
    return int(rom or FALLBACK_PRICE.get(item_id, 0))


def sell_price(item_id: int) -> int:
    return price(item_id) // SELL_DIVISOR
