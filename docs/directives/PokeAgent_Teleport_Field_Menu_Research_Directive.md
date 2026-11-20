# PokeAgent Teleport Field-Menu Research (why no TELEPORT in the Abra submenu)

Repo: PokeAgent (public GitHub rfd62794/Trailswarm, default branch main; queue repo name "PokeAgent"). Branch: `directive/pokeagent-teleport-field-menu`.
Execute-On: cloud (no ROM, no emulator, no network). Research and a small code check only.
Depends on: nothing. Feeds directive 3 (PokeAgent_Glitch_Start_State_Directive.md), which needs this finding.

## 1. Why this exists

The trainer-escape probe (docs/directives/PokeAgent_Glitch_Trainer_Escape_Directive.md, merged in PR #331) needs a party Abra whose
START > POKeMON submenu offers TELEPORT. A controller-verified real-ROM run on 2026-11-19 found:
- The probe save `runs/checkpoints/nugget_bridge.state` boxes an L10 Abra with moves read as `[0x64, 0, 0, 0]` (0x64 = 100 = TELEPORT).
- The Abra was withdrawn to party slot 6 using PC button presses only (no RAM writes).
- Its START > POKeMON > Abra submenu then shows ONLY `STATS / SWITCH / CANCEL`. No TELEPORT, both outdoors on Route 25 and in Cerulean.
  Fly and Dig were absent too (expected: Abra does not know them).
The pret disassembly suggests a mon holding a field move lists it in that submenu. So either our reading is wrong or there is a rule we have not found.
This directive finds out, from the public pret/pokered source pasted below. You cannot browse: EVERYTHING you need is in section 2. Do not search for
more; if something you need is not pasted, say so in the doc under "Open questions".

## 2. Facts (pret/pokered master, fetched 2026-11-19; line numbers are of that fetch and may drift upstream)

### 2a. data/moves/field_moves.asm
```
1: FieldMoveDisplayData:
2: 	; move id, FieldMoveNames index, leftmost tile
3: 	; (leftmost tile = -1 + tile column in which the first
4: 	;  letter of the move's name should be displayed)
5: 	db CUT,        1, $0C
6: 	db FLY,        2, $0C
7: 	db ANIM_B4,    3, $0C ; unused
8: 	db SURF,       4, $0C
9: 	db STRENGTH,   5, $0A
10: 	db FLASH,      6, $0C
11: 	db DIG,        7, $0C
12: 	db TELEPORT,   8, $0A
13: 	db SOFTBOILED, 9, $08
14: 	db -1 ; end
```

### 2b. engine/menus/start_sub_menus.asm: StartMenu_Pokemon (lines 9-86) and the out-of-battle dispatch (104-131, 205-226)
```
9: StartMenu_Pokemon::
10: 	ld a, [wPartyCount]
11: 	and a
12: 	jp z, RedisplayStartMenu
13: 	xor a
14: 	ld [wMenuItemToSwap], a
15: 	ld [wPartyMenuTypeOrMessageID], a
16: 	ld [wUpdateSpritesEnabled], a
17: 	call DisplayPartyMenu
18: 	jr .checkIfPokemonChosen
19: .loop
20: 	xor a
21: 	ld [wMenuItemToSwap], a
22: 	ld [wPartyMenuTypeOrMessageID], a
23: 	call GoBackToPartyMenu
24: .checkIfPokemonChosen
25: 	jr nc, .chosePokemon
26: .exitMenu
27: 	call GBPalWhiteOutWithDelay3
28: 	call RestoreScreenTilesAndReloadTilePatterns
29: 	call LoadGBPal
30: 	jp RedisplayStartMenu
31: .chosePokemon
32: 	call SaveScreenTilesToBuffer1
33: 	ld a, FIELD_MOVE_MON_MENU
34: 	ld [wTextBoxID], a
35: 	call DisplayTextBoxID ; display pokemon menu options
36: 	ld hl, wFieldMoves
37: 	lb bc, 2, 12 ; max menu item ID, top menu item Y
38: 	ld e, 5
39: .adjustMenuVariablesLoop
40: 	dec e
41: 	jr z, .storeMenuVariables
42: 	ld a, [hli]
43: 	and a ; end of field moves?
44: 	jr z, .storeMenuVariables
45: 	inc b
46: 	dec c
47: 	dec c
48: 	jr .adjustMenuVariablesLoop
49: .storeMenuVariables
50: 	ld hl, wTopMenuItemY
51: 	ld a, c
52: 	ld [hli], a ; top menu item Y
53: 	ldh a, [hFieldMoveMonMenuTopMenuItemX]
54: 	ld [hli], a ; top menu item X
55: 	xor a
56: 	ld [hli], a ; current menu item ID
57: 	inc hl
58: 	ld a, b
59: 	ld [hli], a ; max menu item ID
60: 	ld a, PAD_A | PAD_B
61: 	ld [hli], a ; menu watched keys
62: 	xor a
63: 	ld [hl], a
64: 	call HandleMenuInput
65: 	push af
66: 	call LoadScreenTilesFromBuffer1
67: 	pop af
68: 	bit B_PAD_B, a
69: 	jp nz, .loop
70: ; if the B button wasn't pressed
71: 	ld a, [wMaxMenuItem]
72: 	ld b, a
73: 	ld a, [wCurrentMenuItem] ; menu selection
74: 	cp b
75: 	jp z, .exitMenu ; if the player chose Cancel
76: 	dec b
77: 	cp b
78: 	jr z, .choseSwitch
79: 	dec b
80: 	cp b
81: 	jp z, .choseStats
82: 	ld c, a
83: 	ld b, 0
84: 	ld hl, wFieldMoves
85: 	add hl, bc
86: 	jp .choseOutOfBattleMove
```
```
104: .choseOutOfBattleMove
105: 	push hl
106: 	ld a, [wWhichPokemon]
107: 	ld hl, wPartyMonNicks
108: 	call GetPartyMonName
109: 	pop hl
110: 	ld a, [hl]
111: 	dec a
112: 	add a
113: 	ld b, 0
114: 	ld c, a
115: 	ld hl, .outOfBattleMovePointers
116: 	add hl, bc
117: 	ld a, [hli]
118: 	ld h, [hl]
119: 	ld l, a
120: 	ld a, [wObtainedBadges]
121: 	jp hl
122: .outOfBattleMovePointers
123: 	dw .cut
124: 	dw .fly
125: 	dw .surf
126: 	dw .surf
127: 	dw .strength
128: 	dw .flash
129: 	dw .dig
130: 	dw .teleport
131: 	dw .softboiled
```
```
205: .teleport
206: 	call CheckIfInOutsideMap
207: 	jr z, .canTeleport
208: 	ld a, [wWhichPokemon]
209: 	ld hl, wPartyMonNicks
210: 	call GetPartyMonName
211: 	ld hl, .cannotUseTeleportNowText
212: 	call PrintText
213: 	jp .loop
214: .canTeleport
215: 	ld hl, .warpToLastPokemonCenterText
216: 	call PrintText
217: 	ld hl, wStatusFlags6
218: 	set BIT_FLY_WARP, [hl]
219: 	set BIT_ESCAPE_WARP, [hl]
220: 	ld hl, wStatusFlags4
221: 	set BIT_UNKNOWN_4_1, [hl]
222: 	res BIT_NO_BATTLES, [hl]
223: 	ld c, 60
224: 	call DelayFrames
225: 	call GBPalWhiteOutWithDelay3
226: 	jp .goBackToMap
```

### 2c. engine/menus/text_box.asm: DisplayFieldMoveMonMenu (382-410) and GetMonFieldMoves (509-559)
```
382: DisplayFieldMoveMonMenu:
383: 	xor a
384: 	ld hl, wFieldMoves
385: 	ld [hli], a ; wFieldMoves
386: 	ld [hli], a ; wFieldMoves + 1
387: 	ld [hli], a ; wFieldMoves + 2
388: 	ld [hli], a ; wFieldMoves + 3
389: 	ld [hli], a ; wNumFieldMoves
390: 	ld [hl], 12 ; wFieldMovesLeftmostXCoord
391: 	call GetMonFieldMoves
392: 	ld a, [wNumFieldMoves]
393: 	and a
394: 	jr nz, .fieldMovesExist
395: 
396: ; no field moves
397: 	hlcoord 11, 11
398: 	ld b, 5
399: 	ld c, 7
400: 	call TextBoxBorder
401: 	call UpdateSprites
402: 	ld a, 12
403: 	ldh [hFieldMoveMonMenuTopMenuItemX], a
404: 	hlcoord 13, 12
405: 	ld de, PokemonMenuEntries
406: 	jp PlaceString
407: 
408: .fieldMovesExist
409: 	push af
410: 
```
```
509: GetMonFieldMoves:
510: 	ld a, [wWhichPokemon]
511: 	ld hl, wPartyMon1Moves
512: 	ld bc, PARTYMON_STRUCT_LENGTH
513: 	call AddNTimes
514: 	ld d, h
515: 	ld e, l
516: 	ld c, NUM_MOVES + 1
517: 	ld hl, wFieldMoves
518: .loop
519: 	push hl
520: .nextMove
521: 	dec c
522: 	jr z, .done
523: 	ld a, [de] ; move ID
524: 	and a
525: 	jr z, .done
526: 	ld b, a
527: 	inc de
528: 	ld hl, FieldMoveDisplayData
529: .fieldMoveLoop
530: 	ld a, [hli]
531: 	cp $ff
532: 	jr z, .nextMove ; if the move is not a field move
533: 	cp b
534: 	jr z, .foundFieldMove
535: 	inc hl
536: 	inc hl
537: 	jr .fieldMoveLoop
538: .foundFieldMove
539: 	ld a, b
540: 	ld [wLastFieldMoveID], a
541: 	ld a, [hli] ; field move name index
542: 	ld b, [hl] ; field move leftmost X coordinate
543: 	pop hl
544: 	ld [hli], a ; store name index in wFieldMoves
545: 	ld a, [wNumFieldMoves]
546: 	inc a
547: 	ld [wNumFieldMoves], a
548: 	ld a, [wFieldMovesLeftmostXCoord]
549: 	cp b
550: 	jr c, .skipUpdatingLeftmostXCoord
551: 	ld a, b
552: 	ld [wFieldMovesLeftmostXCoord], a
553: .skipUpdatingLeftmostXCoord
554: 	ld a, [wLastFieldMoveID]
555: 	ld b, a
556: 	jr .loop
557: .done
558: 	pop hl
559: 	ret
```

### 2d. engine/pokemon/add_mon.asm: _MoveMon, the PC withdraw / deposit copy (341-427)
```
341: _MoveMon::
342: 	ld a, [wMoveMonType]
343: 	and a   ; BOX_TO_PARTY
344: 	jr z, .checkPartyMonSlots
345: 	cp DAYCARE_TO_PARTY
346: 	jr z, .checkPartyMonSlots
347: 	cp PARTY_TO_DAYCARE
348: 	ld hl, wDayCareMon
349: 	jr z, .findMonDataSrc
350: 	; else it's PARTY_TO_BOX
351: 	ld hl, wBoxCount
352: 	ld a, [hl]
353: 	cp MONS_PER_BOX
354: 	jr nz, .partyOrBoxNotFull
355: 	jr .boxFull
356: .checkPartyMonSlots
357: 	ld hl, wPartyCount
358: 	ld a, [hl]
359: 	cp PARTY_LENGTH
360: 	jr nz, .partyOrBoxNotFull
361: .boxFull
362: 	scf
363: 	ret
364: .partyOrBoxNotFull
365: 	inc a
366: 	ld [hl], a           ; increment number of mons in party/box
367: 	ld c, a
368: 	ld b, 0
369: 	add hl, bc
370: 	ld a, [wMoveMonType]
371: 	cp DAYCARE_TO_PARTY
372: 	ld a, [wDayCareMon]
373: 	jr z, .copySpecies
374: 	ld a, [wCurPartySpecies]
375: .copySpecies
376: 	ld [hli], a          ; write new mon ID
377: 	ld [hl], $ff         ; write new sentinel
378: ; find mon data dest
379: 	ld a, [wMoveMonType]
380: 	dec a
381: 	ld hl, wPartyMons
382: 	ld bc, PARTYMON_STRUCT_LENGTH
383: 	ld a, [wPartyCount]
384: 	jr nz, .addMonOffset
385: 	; if it's PARTY_TO_BOX
386: 	ld hl, wBoxMons
387: 	ld bc, BOXMON_STRUCT_LENGTH
388: 	ld a, [wBoxCount]
389: .addMonOffset
390: 	dec a
391: 	call AddNTimes
392: .findMonDataSrc
393: 	push hl
394: 	ld e, l
395: 	ld d, h
396: 	ld a, [wMoveMonType]
397: 	and a
398: 	ld hl, wBoxMons
399: 	ld bc, BOXMON_STRUCT_LENGTH
400: 	jr z, .addMonOffset2
401: 	cp DAYCARE_TO_PARTY
402: 	ld hl, wDayCareMon
403: 	jr z, .copyMonData
404: 	ld hl, wPartyMons
405: 	ld bc, PARTYMON_STRUCT_LENGTH
406: .addMonOffset2
407: 	ld a, [wWhichPokemon]
408: 	call AddNTimes
409: .copyMonData
410: 	push hl
411: 	push de
412: 	ld bc, BOXMON_STRUCT_LENGTH
413: 	call CopyData
414: 	pop de
415: 	pop hl
416: 	ld a, [wMoveMonType]
417: 	and a ; BOX_TO_PARTY
418: 	jr z, .findOTdest
419: 	cp DAYCARE_TO_PARTY
420: 	jr z, .findOTdest
421: 	ld bc, BOXMON_STRUCT_LENGTH
422: 	add hl, bc
423: 	ld a, [hl] ; hl = Level
424: 	inc de
425: 	inc de
426: 	inc de
427: 	ld [de], a ; de = BoxLevel
```

### 2e. What our code does (verbatim from this repo)
- `src/pokeagent/ramstructs.py` `decode_party_mon`: 44-byte party struct, `moves=tuple(raw[8:12])`, `pp=tuple(raw[29:33])`, `level=raw[33]`.
- `src/pokeagent/data/ram_map.json`: `wPartyMon1` 0xD16B (44 bytes, verified), `wPartyMon6` 0xD247, `wPartyMon6Moves` 0xD24F (4 bytes),
  `wFieldMoves` 0xCD3D, `wNumFieldMoves` 0xCD41, `wFieldMovesLeftmostXCoord` 0xCD42, `wWhichPokemon` 0xCF92, `wMoves` 0xD0DC
  (pret symbols, `"verified": false`: names known, not replay-confirmed).
- `src/pokeagent/ram_symbols.py`: `BOX_COUNT_ADDR = 0xDA80` (wBoxCount), `BOX_SPECIES = 0xDA81` (wBoxSpecies), `BOX_MONS = 0xDA96` (wBoxMons, 33-byte structs).
  `_MoveMon` above copies BOXMON_STRUCT_LENGTH bytes straight across, so the moves sit at +8..+11 in both structs.
- `src/pokeagent/abra_goal.py` `box_species` reads only the species LIST, never box-mon moves. `src/pokeagent/campaign.py` `party_knows_move(emu, move_id)`
  scans `read_party_view(emu).slots[*].moves`. There is NO box-mon decoder in `src/`: the `[0x64,0,0,0]` came from an ad hoc read by the controller
  (the offset it used is unknown; do not assume it was +8 of wBoxMons).
- `tests/rom/test_party_states.py` documents the 33-byte box struct layout (species +0, HP +1/+2, level +3, ...); it is tracked, read it for the layout.

## 3. Scope (exact files, in order)

1. `docs/research/teleport-field-menu.md` (new): the deliverable (section 4A).
2. If, and only if, 4B finds a real decoding bug: the minimal fix in the file that has it, plus a synthetic test in `tests/` (new file, or an addition to
   `tests/test_ramstructs.py`). If 4B finds no bug, NO code is edited and no test is added; say so in the doc.

## 4. The work

### A. The research doc (`docs/research/teleport-field-menu.md`)
Sections, in this order, each backed by the pasted pret excerpts (cite `file:line`, for example `engine/menus/text_box.asm:509-559`):
1. **How the menu is built.** Walk StartMenu_Pokemon -> FIELD_MOVE_MON_MENU -> DisplayFieldMoveMonMenu -> GetMonFieldMoves step by step: which struct it
   reads (`wPartyMon1Moves` + `wWhichPokemon * PARTYMON_STRUCT_LENGTH`), how many moves it scans (the `NUM_MOVES + 1` loop counter), the stop conditions
   (move id 0 ends the scan; a move not in the table is skipped), and where the result lands (`wFieldMoves`, `wNumFieldMoves`).
2. **When TELEPORT is listed.** State plainly from the excerpts: is there ANY badge, map, tileset or inside/outside check at LIST time? (Read 2b and 2c
   carefully: the `wObtainedBadges` check and `CheckIfInOutsideMap` appear only after an entry is CHOSEN, in `.teleport` / `.fly`.) Give a table of what each
   field move needs at USE time (CUT, FLY, SURF, STRENGTH, FLASH badges; DIG uses ESCAPE_ROPE; TELEPORT needs an outside map).
3. **Why the menu could omit TELEPORT.** A ranked list of candidate causes, each with: the pret mechanism or repo fact it rests on, what RAM byte or screen
   fact would confirm or refute it on a real run, and its likelihood (high / medium / low, one line of reasoning). Cover at least:
   a. the party struct's moves are not `[0x64,0,0,0]` (the box read used a wrong offset or box; or the BOX_TO_PARTY copy differed from what we assume);
   b. `wWhichPokemon` was not the Abra's slot when the submenu was built (cursor on another mon), so the scan read a different mon's moves;
   c. the move id is not TELEPORT in FieldMoveDisplayData (0x64 = 100; compare to the `db TELEPORT, 8, $0A` row);
   d. our screen reader parsed the menu wrong: the box grows UPWARD by 2 tile rows per field move (`FieldMoveNames` index 8, leftmost X $0A), so a reader
      that looks only at the bottom rows, or at a fixed row range, sees STATS/SWITCH/CANCEL and misses the move above them;
   e. the submenu was read from a stale tile map (read before the draw after DisplayTextBoxID settled);
   f. anything else you find in the pasted source.
4. **The controller's measurement plan.** The exact cheap RAM reads (addresses from 2e only) to take on the laptop with the Abra's submenu open:
   `wPartyMon6Moves` 0xD24F..0xD252, `wWhichPokemon` 0xCF92, `wFieldMoves` 0xCD3D..0xCD40, `wNumFieldMoves` 0xCD41, and which tile-map rows hold the menu
   (tile map at 0xC3A0, 360 bytes, per `src/pokeagent/explorer/perceive.py`). State what each outcome means (which candidate it confirms). This is a plan for
   the controller; do not run it.
5. **Our decoding** (4B result) and **Open questions** you could not settle from the pasted source.
Keep the doc factual: no ROM bytes, no hex dumps of a ROM, no claim stronger than the source supports (mark inferences "inference").

### B. The decoding check (code, small)
1. Read `decode_party_mon` in `src/pokeagent/ramstructs.py` and `tests/test_ramstructs.py`. Confirm against the pret layout (2d, 2e) that the moves are bytes 8..11
   of the 44-byte party struct and bytes 8..11 of the 33-byte box struct. State the result in the doc.
2. Write NO new box decoder. Only if you find the party decode reading moves from a wrong offset: fix it, and add a synthetic test that builds a 44-byte party
   struct in code with moves `[0x64, 0, 0, 0]` at the correct offset and asserts `decode_party_mon(...).moves == (0x64, 0, 0, 0)` (it must fail before the fix).
   Build the struct with `bytes(...)` arithmetic in the test; no ROM, no file.

## 5. What NOT to do

- No ROM, no emulator, no save state, no kb file, no `roms/` or `runs/` path anywhere in the doc or tests. NEVER commit or publish a ROM, a save state or any
  ROM-derived data (`roms/`, `kb/`, `runs/` are gitignored; keep it so). No hex dumps of ROM content; addresses and move ids as plain integers are fine.
- No network and no fetch: everything is pasted in section 2. Do not search for pret files; list what is missing under Open questions.
- Do not edit `ram_map.json`, `ram_symbols.py`, `party_view.py`, the glitchlab, the explorer, or any directive. No new box decoder.
- Do not implement a TELEPORT use in the agent; this is research.
- Do not assert the cause. Rank candidates; the controller measures on the real ROM.

## 6. Verification

Baseline (run by the directive author in the worktree, Python 3.12.12 via `uv run`, 2026-11-19):
```
uv run pytest -q -p no:cacheprovider -rfEs tests/test_ramstructs.py tests/test_party_view.py tests/test_party_view_constants.py
28 passed, 1 warning in 2.17s
```
After your work the same command must show 28 passed (plus your one new test only if a bug was found, and it must fail without the fix). Then run the full suite
serially once (`uv run pytest -q -p no:cacheprovider -rfEs`, about 5 minutes, the xdist plugin is NOT installed) and paste the final summary line.
Full-suite baseline on origin/main in a fresh worktree without kb/ or roms/ (2026-11-19, `uv run pytest -q -p no:cacheprovider -rfEs`, serial, 5 minutes):
```
1 failed, 3451 passed, 73 skipped, 1 warning in 302.33s (0:05:02)
FAILED tests/test_lead_and_wild_switch.py::test_geodude_fight_pick_uses_the_real_kb_tables
  AssertionError: needs the gitignored kb/rom_tables.json (the laptop verify recipe copies it in)
```
That ONE failure is environmental (the gitignored ROM-derived kb is absent from a cloud worktree) and is the only failure allowed. Any other failure, or any new one, means stop and report it; do not mark done.
The controller's verify lane runs with the kb present and requires 0 failed there.
Doc check: `git diff --stat origin/main` lists `docs/research/teleport-field-menu.md` and nothing else, unless 4B found a bug.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call needing confirmation is rejected and the run ends mid-task. Never require an install, download or fetch. Never read outside the working directory.
- Use `uv run` (Python 3.12), never bare `python`. Run tests serially, focused files first, with `-p no:cacheprovider`.
- Do not search, glob or hunt for missing files: if something this directive names is missing, stop and write why in the Status row.
- Create no scratch or debug files; if one is unavoidable it goes under `.devin-scratch/` and stays (deleting is denied in the sandbox).
- If a tool call is genuinely blocked, stop and write why in the Status row rather than trying another way around it.
- Branch `directive/pokeagent-teleport-field-menu` only. Commit there as you go. Never commit to main, never push, never deploy; only the controller merges.
- Every commit message ends with this trailer line (docs/STANDARDS.md requires it for unsigned commits; the PR #331 gate flagged its absence):
  `Unsigned-Reason: automation without a key; Robert approved agent commits`
- Do not add a `## Queue` block. Free models only where model configuration is touched (it is not here).

## 8. Completion criteria and Report

Done means ALL of: `docs/research/teleport-field-menu.md` exists with the five parts of 4A and every pret claim carrying a `file:line` citation from section 2; the
"Our decoding" result stated; the focused tests show 28 passed (plus the new bug test only if a bug was found); the full suite shows only the baseline's one environmental failure; every commit carries
the Unsigned-Reason trailer; nothing under `roms/`, `runs/`, `kb/` staged. Status row: `Review`, with one line: the top-ranked cause and whether a decoding bug was found.
Report (findings first): (1) the ranked cause list in three lines, (2) whether TELEPORT has any list-time restriction (yes/no, with the citation), (3) the measurement
plan in one paragraph, (4) the test tails, (5) the commit sha.
