# PokeAgent: the full RAM map from pret's symbols, verified on the ROM - and stats awareness (DVs, stat exp)

**Read first:** `src/pokeagent/data/ram_names.json` (72 named addresses today, each with `verified`, `source`,
`evidence`, `sym`), `src/pokeagent/ram.py`, `src/pokeagent/names.py`, `docs/KNOWLEDGE.md`.
**Builder:** a Claude builder on the laptop with web access and the ROM, `baselines/`, `kb/` and copies of
`runs/checkpoints/*.state` (all gitignored). **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "can our engine read more from the RAM? is there extensive online documentation to help our
mapping and detection? Is this something we can explore extending the mapping on?" and, approved: stats awareness
(Gen 1 DVs and Stat Experience).

The documentation exists and is authoritative:
- **pret/pokered** (the full disassembly): `ram/wram.asm`, `ram/hram.asm` name every variable; the repository's
  **`symbols` branch** publishes `pokered.sym` (bank:address -> label) - the existing registry already cites it
  ("pokered.sym (pret, symbols branch)").
- **Data Crystal**, "Pokemon Red: RAM map" (https://datacrystal.tcrf.net/wiki/Pokemon_Red:RAM_map) - a curated
  table with meanings and value encodings.
- Bulbapedia's Gen I Pokemon data structure page (party/box struct layout, DVs, stat experience).
Only 72 addresses are named today, a fraction of WRAM.

## 2. Scope (in order)

1. **Import** `pokered.sym` from pret's `symbols` branch (fetch the raw file; save the fetched file under
   `src/pokeagent/data/pokered.sym.txt` only if its licence permits redistribution - pret is public domain-style;
   check the repo's LICENSE and say what you found; otherwise keep it in the scratchpad and commit only the
   derived JSON). Generate `src/pokeagent/data/ram_map.json`: every WRAM/HRAM label (0xC000-0xDFFF,
   0xFF80-0xFFFE) with `addr`, `size` (distance to the next label, capped and corrected where `wram.asm` gives
   the true size), `sym`, `region` (party, battle, map, menu, text, audio, sprites, event flags, ...),
   `verified: false`. Keep `ram_names.json`'s existing verified entries and evidence; merge, never downgrade.
2. **Struct decoders** `src/pokeagent/ramstructs.py`: party Pokemon (44 bytes; party mon 1 at 0xD16B: species,
   HP, box level, status, types, catch rate, 4 moves, OT id, 3-byte exp at +14 (0xD179 already used), 5 x 2-byte
   stat exp at +17..+26, 2-byte DVs at +27..+28, 4 PP, level at +33, max HP and 4 stats at +34..+43), the 6-slot
   party, wBattleMon / wEnemyMon (incl. stat modifiers), bag and PC item lists, wObtainedBadges, money (BCD),
   Pokedex owned/seen bitfields, play time, current map header (width, height, tileset, warp count + list, sign
   list, sprite list), text/menu state (wCurrentMenuItem, wTopMenuItemY, text box id), event flags (named from the
   sym labels near wEventFlags where pret names them).
3. **Verification harness** `tools/verify_ram.py`: loads checkpoints and runs checks that prove an address means
   what the map says, writing `verified: true` + `evidence` into `ram_map.json` only when a check passes. Examples:
   party species/level/HP vs the known starter at `first_pokemon.state`; money changes after a purchase; badge
   bit after `beat_brock.state`; Pokedex owned count == party species owned; map header width/height vs Pallet
   Town (10x9 blocks = 20x18 tiles); warp list contains the known Pallet doors; battle structs during a battle
   state (`rl_battle.state` is NOT in battle - find or make one: walk into grass from `to_route1.state`).
   Report how many addresses are verified, by region.
4. **Stats awareness** (Robert approved): `pokeagent.explorer.stats`: `dvs(mon)` (Atk/Def/Spd/Spc 0-15, HP DV
   from the low bits), `stat_exp(mon)`, `stat_value(base, dv, stat_exp, level)` (Gen 1 formula); used for
   (a) **catch keep-best**: when a duplicate species is caught, record both DV sets in memory and prefer the
   better one in the party (no box juggling yet - report only), (b) **training preference**: XP-per-map stats
   gain a "stat exp yield" from enemy base stats (from kb species data if the Game Knowledge drain is merged,
   else from wEnemyMon's base stats if present in RAM), (c) snapshot/brain: party panel shows level, HP, DVs and
   stat exp per mon.
5. Expose everything read-only through the existing tooling: `pokeagent brain ram <name|addr|region>` (if Brain
   Tools is merged) or a `tools/ram_query.py` CLI otherwise; MCP `peek` stays as is.

## 3. The work

Generated data is reproducible: `tools/build_ram_map.py <pokered.sym>` regenerates `ram_map.json`; hand
corrections live in a small overrides file applied on top.

## 4. What NOT to do

- No ROM bytes committed; no executables downloaded or run (fetch text files only).
- Do not change behaviour beyond the stats awareness item (4); no thresholds touched.
- No new runtime dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green; tests for every struct decoder on hand-built byte arrays and for `stat_value`
  against known values (e.g. a level-5 starter's stats from a checkpoint).
- `tools/verify_ram.py` output pasted: verified counts by region, and every check that failed.

## 6. Rules for this run

- Branch `directive/pokeagent-ram-map-and-stats-directive` in a scratchpad worktree off main. Never commit to
  `main`. Test command `uv run pytest -q`. Never bare `python`.

## 7. Completion criteria

- [ ] `ram_map.json` generated from pokered.sym and merged with the existing verified entries
- [ ] `ramstructs.py` decoders; `tools/verify_ram.py` with ROM evidence written back
- [ ] stats awareness (DVs, stat exp, stat formula, keep-best record, training yield, party panel)
- [ ] query CLI; tests green; verify output pasted

## 8. Report

Sources used (with URLs and licence note), counts (labels imported, verified by region), test tail, anything that
did not fit.
