# Yellow prep (gated, not playable)

Status 2026-11-13. `pokemon-yellow` is registered (`game/pokemon_yellow.py`) so its ROM can be verified, but
`playable=False`: `run`, `state`, `mcp` and `PyBoyEmulator` refuse it with the gate message, and
`pokeagent check-rom --game pokemon-yellow` verifies the SHA-1 (CC7D0326...) and prints `NOT PLAYABLE YET`
without booting it. Yellow has its OWN memory family `gen1-yellow` (stores land under `runs/gen1-yellow/`,
`kb/gen1-yellow/`) because pret/pokeyellow's WRAM layout differs from pokered's.

## The RAM-symbol seam (built)

- `GameSpec.symbols` names a table in `game.symbols.SYMBOL_TABLES`; `GameSpec.ram_table` names the
  `data/` label-map file. Red and Blue use `gen1-rb` (today's `ram_symbols.py`) and `ram_map.json`.
- `symbol_table(game)` / `ram_lookup.load_map(game)` raise `SymbolTableMissing` for Yellow: they never fall back
  to Red's addresses. Existing code that imports `pokeagent.ram_symbols` constants directly is Red/Blue-only by
  construction; making it game-aware means routing those reads through `symbol_table(game)` (a later, mechanical change).

## What Yellow needs before the gate opens

1. **pokeyellow.sym import**: generate `data/ram_map_yellow.json` (same shape as `ram_map.json`) and register a
   `"gen1-yellow"` function in `SYMBOL_TABLES` returning every name `ram_symbols.py` defines at its Yellow address.
   Mark entries `verified` only after real reads (`tools/ram_checks.py`).
2. **Pikachu-follow mechanics**: Pikachu walks behind the player (sprite slot, collision, the happiness/emotion
   text), is the starter (no choice of Bulbasaur/Charmander/Squirtle, rival picks Eevee), and cannot be
   deposited like another mon. The explorer's NPC/sprite assumptions and the party logic must tolerate it.
3. **Starter and story events**: Oak's lab scene, Pikachu refusing the ball, different gym leader teams, Cerulean/Vermilion
   changes, new trainers; event-flag indices shift with the layout, so `goals.py` flag reads need Yellow's list.
4. **Map differences**: header table, tilesets, warps and wild tables differ; re-run `tools/rom_maps.py` /
   `rom_tables.py` against the Yellow ROM for its own kb under `kb/gen1-yellow/`.
5. **GBC features**: the ROM carries the GBC flag (colour, not needed for play); check the emulator boots in DMG mode
   and `screen=(160, 144)` holds. SGB/GBC palette data must not confuse the screen-text readers.
6. **Compat-check run** (laptop): a clean Yellow run's `maps.json` against the family memory with both address
   tables: `tools/game_compat.py --baseline runs/maps.json --candidate <yellow maps.json> --baseline-addresses
   src/pokeagent/data/ram_map.json --candidate-addresses src/pokeagent/data/ram_map_yellow.json`. `pass` (not
   `insufficient`) plus the Multi_Game plan phase-10 conditions decide the go.

## Cross-family transfer idea (not built)

Even in its own family, Yellow may later READ Red/Blue map geometry (tile layouts, warps) through a mapping layer:
map ids are bare integers whose meaning matches for most towns/routes but not all, so the layer would be an explicit
`yellow_map_id -> family_map_id` table (derived from header comparison, name match and warp topology) with
read-only access to family stores; anything Yellow learns is written only to its own family. Facts that disagree
become Yellow's overlay, as for Blue. This needs the compat report as its evidence base.

## Opening the gate

Flip `playable=True` (and clear `gate`) only in the PR that lands items 1-4 and the clean compat run. Until then
`tests/test_game_blue_yellow.py` pins the refusal.
