# Plan: a Red/Blue to Yellow translation layer

Status: draft for the laptop run, 2026-11-12. Research and design only; no production code. Robert, 2026-11-12: "We definitely want a translation layer between Red/Blue and Yellow planned and explored."

Context: Red and Blue share the `gen1-pokemon` memory family; Yellow is prepped as its own family `gen1-yellow` (`src/pokeagent/game/spec.py`, `game/stores.py`) because its WRAM differs. This plan says what the two families can share through a translation layer, and how the laptop (which has the ROMs) proves it.

## Evidence base (all fetched 2026-11-12)

- pret/pokered `symbols` branch `pokered.sym` and `ram/wram.asm`, `constants/`, `data/` at master a7b6c19 (2026-11-12). pret/pokeyellow `symbols` branch `pokeyellow.sym`, master b452f2a (2026-11-01). I diffed both repos' source trees and symbol files locally with scripts (not committed). pokeyellow `roms.sha1`: `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1` (Yellow UE, CGB).
- Data Crystal, "Pokemon Yellow/RAM map" (edited 2026-07-29, a stub): "Most of the RAM map (but not all) for this game has an offset of -1 from the one on Red and Blue." Confirmed and sharpened below.
- Bulbapedia returned HTTP 403 to the fetch tool; the Pikachu and gift facts below come from the pokeyellow source instead (stronger). Secondary: Twinfinite and NationalDex Yellow-differences pages (search, 2026-11-12) agree on Pikachu-as-starter and the three gift starters.

**How the counts were made.** The counts in sections 1-4 come from a diff of the pret/pokered (2026-11-12) and pret/pokeyellow (2026-11-01) `.sym` files and source trees: labels by address, map constants and headers, blocks, objects, wild and trainer tables, and event constants. The diff scripts were run locally and are not committed. The counts are approximate. The P1 compat-diff tool will re-derive them and check them against the built ROMs.

## 1. RAM: one shift, not scattered

Measured on the two `.sym` files: WRAM has 2,594 labels in common. **1,210 sit at the same address (0xC000-0xCF1A) and 1,384 sit exactly 1 byte lower in Yellow (0xCF1B-0xDEE2, starting at `wOnSGB`).** Zero labels moved by any other amount. HRAM: 164 of 169 are identical (incl. `hJoyHeld` 0xFFB4, `hJoyPressed` 0xFFB3); five moved (`hJoyInput` 0xFFF8 to 0xFFF5, `hDisableJoypadPolling` 0xFFF9 to 0xFFF8, `hClearLetterPrintingDelayFlags`, `hUILayoutFlags`, `hFieldMoveMonMenuTopMenuItemX`). Yellow adds 382 WRAM labels, nearly all Pikachu, animated-object, printer, surfing-minigame and CGB palette state, none of which Trailswarm reads today.

| symbol | Red | Yellow |
|---|---|---|
| wCurrentMenuItem, wTileMap, wJoyIgnore | CC26, C3A0, CD6B | same |
| wBattleMon / wEnemyMon | D014 / CFE5 | D013 / CFE4 |
| wIsInBattle, wCurOpponent, wTrainerClass | D057, D059, D031 | D056, D058, D030 |
| wPartyCount / wPartyMon1 | D163 / D16B | D162 / D16A |
| wBagItems, wPlayerMoney, wObtainedBadges | D31E, D347, D356 | D31D, D346, D355 |
| wCurMap, wYCoord, wXCoord | D35E, D361, D362 | D35D, D360, D361 |
| wGrassRate / wGrassMons | D887 / D888 | D886 / D887 |
| wEventFlags | D747 | D746 |
| wToggleableObjectFlags (the "missable" flags; renamed in current pret) | D5A6 | D5A5 |
| wPikachuHappiness, wPikachuMood, wPlayerIsTalkingToPikachu | none | D46F, D470, D435 |

Struct layouts (party_struct 44 bytes, battle_struct 29) are unchanged by the label diff; a laptop ROM check should still assert them.

**Seam.** `src/pokeagent/data/ram_map.json` (2,792 rows) is already keyed by symbol (`name`/`sym` plus `addr`); what it lacks is a second address column. `src/pokeagent/ram_symbols.py` is the problem: it hard-codes Red hex (`PARTY_COUNT = 0xD163` ...), and about 51 modules under `src/` contain `0xD...` literals. Translation is therefore "same symbol, different address", provided those constants become `addr(symbol)` lookups. Sensible shape: `ram_map.json` stays the Red/`gen1-pokemon` table; a generated `ram_map_yellow.json` (from `pokeyellow.sym`) is selected through the game spec, with the first-class rule "same name, `addr` from the active game".

## 2. Maps: ids identical, geometry mostly identical

- `constants/map_constants.asm`: the 249 shared ids are identical. Only two differences: id 0x3F is `CERULEAN_TRADE_HOUSE` in Red and `CERULEAN_MELANIES_HOUSE` in Yellow, and Yellow appends 0xF8 `SUMMER_BEACH_HOUSE` (new beach-house tileset). `data/maps/headers/*.asm` are byte-identical apart from those two files.
- `data/trainers`, `gfx/blocksets` and `data/tilesets`: overworld blocksets and every shared tileset's collision are identical; only `gym.bst` and `pokecenter.bst` differ, plus the new BeachHouse tileset.
- `maps/*.blk` (layouts): 29 differ, mostly Pokecenters and Marts (Pikachu-friendly layout), plus Celadon Gym, Celadon Hotel, Game Corner, Cerulean Caves 1F/2F/B1F, Route 4, Route 19.
- `data/maps/objects`: 52 shared maps differ in warps, signs or NPCs. **Warp destination indices shift**: Route 11/12/15/16/18, Route 5-9 gates and Route 2 point at different warp numbers (Route 2 gains a warp to the gate; Route 11's gate warps are `1`/`3` in Yellow, `2`/`4` in Red). Route 19 gains the Summer Beach House door and its sign and swimmers move; Pallet Town's Oak moves (8,5 to 10,4); Oak's Lab has one Eevee ball, not three starters; Route 24 and Cerulean City change.
- Wild tables: 54 of 59 per-map files differ (Route 19/20 are split; Red uses `SeaRoutes`). Trainer parties: `data/trainers/parties.asm` differs in 130 lines.

## 3. Events and flags

`wEventFlags` is a bit array that is not byte-identical across games: by my parse of `event_constants.asm` (indices approximate; the tool recomputes them), the first 1,360 event indices agree, then a handful shift (20 indices by +1 or -6 around Route 25 / Bill's house). 22 events are Yellow-only: `EVENT_GOT_BULBASAUR_IN_CERULEAN`, `EVENT_GOT_SQUIRTLE_FROM_OFFICER_JENNY`, `EVENT_GOT_CHARMANDER_ON_ROUTE_24`, `EVENT_COMPLETED_CATCH_TRAINING` (x3), `EVENT_PLAYER_AT_RIGHT_EXIT_TO_PALLET_TOWN`, `EVENT_SPAWNED_OLD_MAN_1`, the Jessie and James sets (Pokemon Tower 7F, Mt Moon B2F, Rocket Hideout B4F, Silph Co 11F), Viridian Forest trainers 3 and 4; 7 Red-only trainer events disappear. `wGameProgressFlags` ends one byte lower (follows the global shift). Flags are keyed by constant name, so the translation table is `EVENT_NAME -> (red_index, yellow_index | None)`.

## 4. Rosters (never shared)

Yellow-derived values (pokeyellow `data/trainers/parties.asm` vs pokered, 2026-11-12): Brock Geodude/Onix L10/12 (Red 12/14); Lt. Surge a single Raichu L28 (Red Voltorb 21, Pikachu 18, Raichu 24); Erika Tangela 30, Weepinbell 32, Gloom 32 (Red Victreebel 29/Tangela 24/Vileplume 29); Koga four Venonat-line L44-50 (Red Koffing/Muk/Weezing); Sabrina Abra/Kadabra/Alakazam L50 (Red 38-43); Blaine Ninetales/Rapidash/Arcanine (Red had Growlithe and Ponyta); rival's partner is an Eevee evolution line, Pidgey line becomes Spearow/Sandshrew. Misty, Lorelei, Lance match. The Red-based training-spot ledger and `team_floor` values would therefore be wrong for Yellow gyms.

## 5. Mechanics

Source: pokeyellow `home/overworld.asm`, `engine/pikachu/*`, `ram/wram.asm`. Pikachu is a real sprite (`PIKACHU_SPRITE_INDEX`, the last sprite slot) driven by a follow-command buffer (`wPikachuFollowCommandBuffer`, D437); pressing A on it sets `wPlayerIsTalkingToPikachu` (D435 is the 0xFF flag) and opens its emotion/dialog route; `wPikachuCollisionCounter` shows it collides with the player. `ShouldPikachuSpawn` hides it on bike or surf, and when it is not alive in the party. A Pikachu pokeball icon exists only for Pokemon Center healing graphics (`OverworldPikachuBallGFX`); I found no code that makes Pikachu refuse a Poke Ball, so treat that claim as unverified until the laptop test. Yellow ROM is CGB-enhanced (`home/cgb_palettes.asm`, `hOnCGB`), so PyBoy renders colour and `pixelrefs.json` / `pixelsig.py` ink signatures need re-capture per game; tile decoding should be unaffected.

## Design: three buckets

**Transfers as advisory (`translated`):** map geometry and walls for the maps whose `.blk`, blockset and header are byte-identical (found by the compat tool, not assumed); learned routes through them; "where things are" (Pokemon Centers, gyms, exits) with the Yellow warp-index remap applied; map names and ids (except 0x3F, 0xF8).
**Through mapping tables:** symbol to address (`ram_map_yellow.json`); event name to bit index; warp (map, index) to (map, index); map id (identity table plus two exceptions); sprite object ids per map.
**Never transfers:** wild-encounter tables and the encounter ledger, trainer parties, gym and team floors, story-event expectations (which flags should be set at a stage), starter and gift logic, save states (they stay `game`-scoped in `stores.py`), and any pixel signature.

**Confidence.** Align with the RAM Trust Tiers directive (`sym | verified | caveat | discovered`): add a per-fact `provenance` of `translated` (copied through a table, advisory, never gates an action by itself), promoted to `verified` once a Yellow run observes the same fact (a route walked, a warp taken, a tile blocked), and demoted to `caveat` with a `valid when` note on contradiction. A translated map row carries `from_family: gen1-pokemon` and the compat-diff `sha` of the table that produced it.
**Plug-in points:** `game/stores.py` already separates family and game scope; the layer is a read-through (family `gen1-yellow` store, fallback to translated rows of `gen1-pokemon`, never written back). RAM seam as above. `maps.json` rows gain `provenance` and `source_family`.

## Exploration (laptop, needs the ROMs; never commit them)

**Job A, compat-diff tool** (`tools/compat_diff.py`, reuse `atlas/rom_maps.py` + `tools/rom_tables.py` + `tools/rom_maps.py`): given Red and Yellow ROMs, diff map headers, blocks, blocksets, collision, warps, signs, objects, wild and trainer tables, `wEventFlags` names (from the two `.sym` files); emit `kb/compat/red_yellow.json` mapping tables plus a human report and its own confidence per map (`identical | warps-remapped | layout-differs`). Note `atlas/rom_maps.py` hard-codes Red header table addresses (`PTRS 0x01AE`, `BANKS 0xC23D`); Yellow's differ, so take them from `pokeyellow.sym`.
**Job B, ROM-assert RAM translation:** with Yellow booted, assert 20 key symbols at the translated addresses (party after getting Pikachu, map id, X/Y, badges, money, bag, flags), flipping rows to `verified` for `gen1-yellow`.
**Job C, research run:** Yellow from its start in two arms: (1) translated Red/Blue memory, (2) empty. Score order: goals reached, then steps, then actions; same seed set, equal budget, repeat 3x; also count translated facts promoted and contradicted.

**Phases:** P0 sym-keyed address table plus `ram_symbols.py` seam (Red-identical, golden trace unchanged); P1 Job A; P2 Yellow family boot plus Job B; P3 read-through `translated` rows; P4 Job C, then keep or drop the layer by its result.

## Open questions only the ROM diff can answer

1. Are the `.blk` diffs in the 29 maps real layout changes or only palette/Pikachu decoration, and do any alter walkability? 2. Yellow's `MapHeaderPointers` and bank table addresses. 3. Do warp-index shifts match the source diff (Route 2, Route 11)? 4. Exact `wEventFlags` index map from the built ROM (my parse is approximate). 5. Is `wToggleableObjectFlags` semantics unchanged, and does `wMissable...` data differ per map? 6. Does Pikachu ever block a 1-tile corridor or fail a Poke Ball? 7. Under PyBoy CGB, what do `pixelrefs.json` signatures look like, and does `Emulator.gen1` still detect the ROM?
