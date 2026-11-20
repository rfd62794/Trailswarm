# Why the Abra submenu showed no TELEPORT (research)

Source: pret/pokered master (line numbers match the section 2 excerpts of the directive; re-checked against a fresh shallow clone).
No ROM, emulator or save state was used. Statements marked *inference* go beyond the source.

## 1. How the menu is built

1. `StartMenu_Pokemon` (`engine/menus/start_sub_menus.asm:9-18`) shows the party menu. When a mon is chosen (`:31-35`) it sets
   `wTextBoxID = FIELD_MOVE_MON_MENU` and calls `DisplayTextBoxID`, which dispatches to `DisplayFieldMoveMonMenu`
   (`data/text_boxes.asm:5`).
2. `DisplayFieldMoveMonMenu` (`engine/menus/text_box.asm:382-391`) zeroes `wFieldMoves[0..3]`, `wNumFieldMoves`, sets
   `wFieldMovesLeftmostXCoord = 12`, then calls `GetMonFieldMoves`.
3. `GetMonFieldMoves` (`text_box.asm:509-559`) reads the **party** struct: `wPartyMon1Moves + wWhichPokemon * PARTYMON_STRUCT_LENGTH`
   (`:510-513`). It scans at most `NUM_MOVES + 1` iterations of `dec c` (`:516,521`), i.e. up to the 4 move slots.
   Stop conditions: move id 0 ends the scan (`:523-525`); a move id absent from `FieldMoveDisplayData` is skipped (`:531-532`).
   A match stores the **name index** (not the move id) into `wFieldMoves` (`:541-544`), increments `wNumFieldMoves` (`:545-547`)
   and tracks the minimum leftmost X (`:548-552`).
4. Back in `DisplayFieldMoveMonMenu`: if `wNumFieldMoves == 0` the small box is drawn at (11,11) with STATS/SWITCH/CANCEL at (13,12)
   (`:392-406`). Otherwise (`:408-503`) the box top moves **up 2 tile rows per field move plus 1 extra row** (`:424-440`), the field
   move names are printed from `FieldMoveNames` at 2-row spacing starting above row 12 (`:442-478`), and STATS/SWITCH/CANCEL are
   printed at row 12 (`:480-499`). So with one field move the field-move name sits at tile row 10 and STATS/SWITCH/CANCEL at rows 12/14/16
   (*inference from the coordinate arithmetic*; the box is wider to the left, leftmost X $0A for TELEPORT, `data/moves/field_moves.asm:12`).
5. `StartMenu_Pokemon` then sets the menu cursor (`start_sub_menus.asm:36-64`): max item id = 2 + number of field moves
   (counted via the `wFieldMoves` loop, `:39-48`, capped by `e = 5`), top Y moved up 2 per field move.

## 2. When TELEPORT is listed

**No list-time restriction exists in the pasted source.** The only gate at list time is "the mon's party-struct move id is in
`FieldMoveDisplayData`" (`text_box.asm:526-537`), where TELEPORT is `db TELEPORT, 8, $0A` (`data/moves/field_moves.asm:12`;
`TELEPORT = $64 = 100`, `constants/move_constants.asm:108`). No badge, map, tileset or inside/outside test occurs in
`DisplayFieldMoveMonMenu` or `GetMonFieldMoves`. Badge and map checks run only after an entry is chosen
(`start_sub_menus.asm:104-121` loads `wObtainedBadges` then jumps to the per-move handler).

Use-time requirements (`start_sub_menus.asm`, handlers after `:122-131`):

| Move | Needs at USE time | Citation |
|---|---|---|
| CUT | Cascade badge | `.cut` (`bit BIT_CASCADEBADGE`) |
| FLY | Thunder badge (+ town map conditions) | `.fly` (`bit BIT_THUNDERBADGE`) |
| SURF | Soul badge | `.surf` (`bit BIT_SOULBADGE`) |
| STRENGTH | Rainbow badge | `.strength` (`bit BIT_RAINBOWBADGE`) |
| FLASH | Boulder badge | `.flash` (`bit BIT_BOULDERBADGE`) |
| DIG | An ESCAPE_ROPE-style use (`ld a, ESCAPE_ROPE`) | `.dig` |
| TELEPORT | Outside map: `CheckIfInOutsideMap` z flag, else "cannot use now" text and back to menu | `:205-213`; `home/overworld.asm:705-` |
| SOFTBOILED | A party mon to give HP to | `.softboiled` |

So a cannot-teleport state (indoors, no badge) would still **list** TELEPORT. Being outdoors on Route 25 and in Cerulean makes the
use-time check pass anyway; neither is a cause.

## 3. Why the menu could omit TELEPORT (ranked)

1. **(d) Our screen read missed the row above STATS. Likelihood: high.** The game draws TELEPORT at tile row ~10, above
   STATS/SWITCH/CANCEL (rows 12-16, `text_box.asm:424-440, 442-478`). A reader scanning a fixed bottom range, or the
   "no field moves" layout (rows 11-17, `:397-406`), sees exactly STATS/SWITCH/CANCEL. Fly/Dig not showing is consistent
   (Abra does not know them), so this single observation does not discriminate. Confirm/refute: `wNumFieldMoves` (0xCD41) = 1 and
   `wFieldMoves[0]` (0xCD3D) = 8 with menu open while the tile map shows only three entries at rows 12/14/16 and a tile row 10 string.
2. **(a) The party struct's moves are not `[0x64,0,0,0]`. Likelihood: medium.** The 0x64 came from an ad hoc box read
   with an unknown offset (no box decoder in `src/`). Box moves are +8..+11 (`macros/ram.asm` `box_struct`: species, HP(2), BoxLevel,
   Status, Type1, Type2, CatchRate, Moves), and `_MoveMon` copies `BOXMON_STRUCT_LENGTH` bytes straight across
   (`engine/pokemon/add_mon.asm:410-413`), so a correct withdraw preserves them (*inference: later party-only fields such as stats are
   recomputed after the copy, not shown in the excerpt*). A wrong offset or a different box slot could have yielded 0x64 by accident.
   Confirm: read 0xD24F..0xD252 with submenu open.
3. **(b) `wWhichPokemon` was not the Abra's slot. Likelihood: medium-low.** The scan indexes by `wWhichPokemon` (`text_box.asm:510-513`).
   If the cursor/slot variable pointed to another mon the scan read that mon's moves. Party menu sets it on selection; stale value
   possible if the controller drove the menu by raw input timing. Confirm: 0xCF92 should be 5 (0-based slot 6).
4. **(e) Stale tile map. Likelihood: medium-low.** The menu is drawn by `TextBoxBorder` + `PlaceString` calls
   (`text_box.asm:440-499`) after `DisplayTextBoxID`; a read between the box border and the printed names, or from a buffer not yet
   copied to the screen tilemap, shows partial text. (*inference*) Confirm: re-read tile map several frames later, and compare with
   `wNumFieldMoves`.
5. **(c) Move id not TELEPORT. Likelihood: low.** 0x64 = 100 = TELEPORT (`move_constants.asm:108`); table row `field_moves.asm:12`.
   Only matters if the real move bytes differ (covered by cause 2).
6. **(f) Other.** If `wPartyCount` were 0 the whole menu would not open (`start_sub_menus.asm:10-12`); not the case since the submenu
   showed. Slot 6 specifics: `GetMonFieldMoves` uses `AddNTimes` with the slot index, no 5-slot limit seen. Nothing else found.

**Verdict: most likely cause is (d), a screen reader that never looked at the row above STATS/SWITCH/CANCEL**, pending the RAM check.

## 4. Controller measurement plan (laptop, Abra submenu open; do not run in cloud)

With the Abra's START > POKeMON submenu on screen, read: `wPartyMon6Moves` 0xD24F..0xD252 (4 bytes); `wWhichPokemon` 0xCF92;
`wFieldMoves` 0xCD3D..0xCD40; `wNumFieldMoves` 0xCD41; `wFieldMovesLeftmostXCoord` 0xCD42; and the 360-byte tile map at 0xC3A0
(20 columns x 18 rows, `explorer/perceive.py`), decoding rows 8-17, columns 9-19.
Outcomes:
- 0xD24F = 100, 0xCF92 = 5, 0xCD41 = 1, 0xCD3D = 8, tile rows 10 shows "TELEPORT": menu is fine, the earlier reader was wrong (d) or stale (e).
- 0xD24F..0xD252 not containing 100: cause (a); re-read the box struct at wBoxMons + 33*slot + 8.
- 0xD24F = 100 but 0xCF92 != 5: cause (b).
- 0xD24F = 100, 0xCF92 = 5, 0xCD41 = 0: contradicts the pasted source; list as an open question (maybe a different build).
- 0xCD41 = 1 but tile rows 10-11 blank: stale or mis-timed tile map read (e).

## 5. Our decoding and open questions

`decode_party_mon` (`src/pokeagent/ramstructs.py:49-61`) reads `moves=raw[8:12]`, `pp=raw[29:33]`, `level=raw[33]` from the
44-byte struct. That matches the pret layout: moves at +8..+11 in `box_struct` and the party struct embeds `box_struct` first
(`macros/ram.asm`, `party_struct`), and `_MoveMon` copies the 33-byte box struct to the same offsets
(`add_mon.asm:410-413`). `tests/test_ramstructs.py` and `tests/rom/test_party_states.py` pin moves at +8 for both structs.
**No decoding bug was found; no code or test was changed.**

Open questions: (1) how the controller's ad hoc box read derived 0x64; (2) the exact tile rows our screen reader inspects
(not pasted); (3) the `FieldMoveNames` string table and `CalcStats` post-withdraw behaviour were not in the pasted excerpts.
