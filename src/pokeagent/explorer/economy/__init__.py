"""economy: buying supplies, using them outside battle, and keeping the money books (Economy v1).

Pure rules live here; the walking and the shop button presses stay in behaviours/restock.py and shop.py.
  prices      item ids, ROM prices (kb/rom_tables.json, never committed) with Gen 1 fallbacks, the Nugget sell whitelist
  hp_stats    expected HP loss per segment from runs/battles.jsonl (party_before/party_after)
  budget      the reserve that is never spent
  shopping    shopping_list(goals, bag, money, party, stats) -> [(item, qty)]
  bundles     candidate shopping bundles (the seam for a future bandit decision; not wired)
  ledger      income / spend / blackout losses, the Pokecenters visited, the purchase log
  outside_use drink a Potion instead of walking to a Pokecenter when the walk costs more than the Potion
"""
