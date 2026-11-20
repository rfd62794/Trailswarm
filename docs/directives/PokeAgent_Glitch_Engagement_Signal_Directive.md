# PokeAgent Glitch Engagement Signal: a reliable "trainer engaged" read for the probe and the survey

Repo: PokeAgent (public GitHub rfd62794/Trailswarm, default branch main; queue repo name "PokeAgent"). Branch: `directive/pokeagent-glitch-engagement-signal`.
Execute-On: cloud (synthetic tests only, no ROM). Real-ROM validation is a CONTROLLER step listed in section 8; do not attempt it.
Depends on: PR #331 (trainer-escape probe) being on main. It is: `src/pokeagent/glitch_signals.py`, `src/pokeagent/glitchlab/*` and `tools/glitch_probe.py` exist on origin/main.
If `src/pokeagent/glitchlab/survey.py` is missing, STOP and write "slice 2 not merged" in the Status row.

## 1. Why this exists

The first real-ROM run of the probe (controller-verified, 2026-11-19, on `runs/checkpoints/nugget_bridge.state`, input state byte-identical afterwards) produced:
```
{"start_opened_before_engagement": false, "trainer_state_stuck": false, "enemy_special": {"special_u16": 21, "special_lo": 21},
 "instant_encounter": null, "species_matches_special": null,
 "notes": ["bit meanings UNVERIFIED", "at_exclaim engaged_class=21", "after_escape misc_flags=0 status5=0 in_battle=False map=36"]}
```
Two findings make the current engagement signal unusable:
1. `engaged_class` (wEngagedTrainerClass, 0xCD2D) reads NONZERO with NO trainer engaged: 21 on Route 25, 14 and 230 in Cerulean. So `at_exclaim engaged_class=21` and
   the survey's `max_engage_dist: 6` for every trainer with `start_before_engage: false` everywhere are ARTIFACTS, not measurements. `wMiscFlags` (0xCD60) and
   `wStatusFlags5` (0xD730) stayed 0 because no engagement happened. Why (from the pokered source pasted in 2a-2b): wEngagedTrainerClass is written only by
   EngageMapTrainer and is never cleared afterwards, so it holds the LAST engaged value (a stale byte). Values 21 and 14 are also below OPP_ID_OFFSET (the
   class test `cp OPP_ID_OFFSET`, trainers.asm:230; our own `tools/rom_world.py` reads a trainer class as `data[p] - 200`), so they are not trainer classes at all
   (inference: the byte is stale or shared). Do not use it as a level signal.
2. The survey (`src/pokeagent/glitchlab/survey.py`, `approach_steps`) presses UP from a fixed state for every trainer regardless of where the trainer stands or
   faces. It cannot engage anyone it is not already lined up with.
A side effect to REPORT (not fix here): `active_reasons` in `src/pokeagent/glitch_signals.py` flags `trainer_flags_stuck` only when
`engaged_class == 0 and engaged_set == 0`. With engaged_class stale and nonzero, that rule can stay silent on a genuinely stuck state. Changing a guard rule is
a separate decision for the controller; see section 4.D.

Also on the probe save: it has EVERY Route 24 (map 0x23) and Route 25 (0x24) trainer already beaten; the only unbeaten trainer seen was a Cerulean Rocket NPC. A beaten
trainer is skipped by the engine (trainers.asm:272-277), so a survey of that save SHOULD report no engagement. That is the correct answer, not a failure.

## 2. Facts (pret/pokered master, fetched 2026-11-19; line numbers may drift upstream; you cannot browse, everything needed is here)

### 2a. engine/overworld/trainer_sight.asm: TrainerEngage (164-232) and the sight-line check (257-290)
```
164: TrainerEngage:
165: 	push hl
166: 	push de
167: 	ld a, [wTrainerSpriteOffset]
168: 	add SPRITESTATEDATA1_IMAGEINDEX
169: 	ld d, $0
170: 	ld e, a
171: 	ld hl, wSpriteStateData1
172: 	add hl, de
173: 	ld a, [hl]             ; x#SPRITESTATEDATA1_IMAGEINDEX
174: 	sub $ff
175: 	jr nz, .spriteOnScreen ; test if sprite is on screen
176: 	jp .noEngage
177: .spriteOnScreen
178: 	ld a, [wTrainerSpriteOffset]
179: 	add SPRITESTATEDATA1_FACINGDIRECTION
180: 	ld d, $0
181: 	ld e, a
182: 	ld hl, wSpriteStateData1
183: 	add hl, de
184: 	ld a, [hl]             ; x#SPRITESTATEDATA1_FACINGDIRECTION
185: 	ld [wTrainerFacingDirection], a
186: 	call ReadTrainerScreenPosition
187: 	ld a, [wTrainerScreenY]          ; sprite screen Y pos
188: 	ld b, a
189: 	ld a, $3c
190: 	cp b
191: 	jr z, .linedUpY
192: 	ld a, [wTrainerScreenX]          ; sprite screen X pos
193: 	ld b, a
194: 	ld a, $40
195: 	cp b
196: 	jr z, .linedUpX
197: 	xor a
198: 	jp .noEngage
199: .linedUpY
200: 	ld a, [wTrainerScreenX]        ; sprite screen X pos
201: 	ld b, a
202: 	ld a, $40            ; (fixed) player X position
203: 	call CalcDifference  ; calc distance
204: 	jr z, .noEngage      ; exact same position as player
205: 	call CheckSpriteCanSeePlayer
206: 	jr c, .engage
207: 	xor a
208: 	jr .noEngage
209: .linedUpX
210: 	ld a, [wTrainerScreenY]        ; sprite screen Y pos
211: 	ld b, a
212: 	ld a, $3c            ; (fixed) player Y position
213: 	call CalcDifference  ; calc distance
214: 	jr z, .noEngage      ; exact same position as player
215: 	call CheckSpriteCanSeePlayer
216: 	jr c, .engage
217: 	xor a
218: 	jp .noEngage
219: .engage
220: 	call CheckPlayerIsInFrontOfSprite
221: 	ld a, [wTrainerSpriteOffset]
222: 	and a
223: 	jr z, .noEngage
224: 	ld hl, wMiscFlags
225: 	set BIT_SEEN_BY_TRAINER, [hl]
226: 	call EngageMapTrainer
227: 	ld a, $ff
228: .noEngage
229: 	ld [wTrainerSpriteOffset], a
230: 	pop de
231: 	pop hl
232: 	ret
```
```
257: CheckSpriteCanSeePlayer:
258: 	ld b, a
259: 	ld a, [wTrainerEngageDistance] ; how far the trainer can see
260: 	cp b
261: 	jr nc, .checkIfLinedUp
262: 	jr .notInLine         ; player too far away
263: .checkIfLinedUp
264: 	ld a, [wTrainerFacingDirection]         ; sprite facing direction
265: 	cp SPRITE_FACING_DOWN
266: 	jr z, .checkXCoord
267: 	cp SPRITE_FACING_UP
268: 	jr z, .checkXCoord
269: 	cp SPRITE_FACING_LEFT
270: 	jr z, .checkYCoord
271: 	cp SPRITE_FACING_RIGHT
272: 	jr z, .checkYCoord
273: 	jr .notInLine
274: .checkXCoord
275: 	ld a, [wTrainerScreenX]         ; sprite screen X position
276: 	ld b, a
277: 	cp $40
278: 	jr z, .inLine
279: 	jr .notInLine
280: .checkYCoord
281: 	ld a, [wTrainerScreenY]         ; sprite screen Y position
282: 	ld b, a
283: 	cp $3c
284: 	jr nz, .notInLine
285: .inLine
286: 	scf
287: 	ret
288: .notInLine
289: 	and a
290: 	ret
```

### 2b. home/trainers.asm: the per-map trainer loop (262-301), EngageMapTrainer (320-332), end-of-fight clear (185-190), InitBattleEnemyParameters (226-231)
```
262: .trainerLoop
263: 	call StoreTrainerHeaderPointer
264: 	ld a, [de]
265: 	ld [wSpriteIndex], a
266: 	ld [wTrainerHeaderFlagBit], a
267: 	cp -1
268: 	ret z
269: 	ld a, TRAINER_EVENT_FLAG_POINTER
270: 	call ReadTrainerHeaderInfo
271: 	ld b, FLAG_TEST
272: 	ld a, [wTrainerHeaderFlagBit]
273: 	ld c, a
274: 	call TrainerFlagAction
275: 	ld a, c
276: 	and a ; has the trainer already been defeated?
277: 	jr nz, .continue
278: 	push hl
279: 	push de
280: 	push hl
281: 	xor a ; TRAINER_EVENT_FLAG_BIT
282: 	call ReadTrainerHeaderInfo
283: 	inc hl
284: 	ld a, [hl]
285: 	pop hl
286: 	ld [wTrainerEngageDistance], a
287: 	ld a, [wSpriteIndex]
288: 	swap a
289: 	ld [wTrainerSpriteOffset], a
290: 	predef TrainerEngage
291: 	pop de
292: 	pop hl
293: 	ld a, [wTrainerSpriteOffset]
294: 	and a
295: 	ret nz ; break if the trainer is engaging
296: .continue
297: 	ld hl, TRAINER_STRUCT_SIZE
298: 	add hl, de
299: 	ld d, h
300: 	ld e, l
301: 	jr .trainerLoop
```
```
320: EngageMapTrainer::
321: 	ld hl, wMapSpriteExtraData
322: 	ld d, 0
323: 	ld a, [wSpriteIndex]
324: 	dec a
325: 	add a
326: 	ld e, a
327: 	add hl, de
328: 	ld a, [hli]
329: 	ld [wEngagedTrainerClass], a
330: 	ld a, [hl]
331: 	ld [wEngagedTrainerSet], a
332: 	jp PlayTrainerMusic
```
```
185: 	ld hl, wMiscFlags
186: 	res BIT_SEEN_BY_TRAINER, [hl]
187: 	ld a, [wIsInBattle]
188: 	cp LOST_BATTLE
189: 	jp z, ResetButtonPressedAndMapScript
190: 	ld a, TRAINER_EVENT_FLAG_POINTER
```
```
226: InitBattleEnemyParameters::
227: 	ld a, [wEngagedTrainerClass]
228: 	ld [wCurOpponent], a
229: 	ld [wEnemyMonOrTrainerClass], a
230: 	cp OPP_ID_OFFSET
231: 	ld a, [wEngagedTrainerSet]
```

### 2c. constants/ram_constants.asm: wMiscFlags bit names
```
6: ; wMiscFlags
7: 	const_def
8: 	const BIT_SEEN_BY_TRAINER      ; 0
9: 	const BIT_BOULDER_DUST         ; 1
10: 	const BIT_TURNING              ; 2
11: 	const BIT_USING_GENERIC_PC     ; 3
12: 	const BIT_NO_SPRITE_UPDATES    ; 4
```

### 2d. What this means (derived from 2a-2c; mark as inference in code comments where it is)
- `BIT_SEEN_BY_TRAINER` is wMiscFlags (0xCD60) bit 0. TrainerEngage sets it (trainer_sight.asm:224-225) immediately before `EngageMapTrainer`, i.e. at the moment a trainer
  spots the player; EndTrainerBattle clears it (trainers.asm:185-186). It is a per-engagement signal, unlike wEngagedTrainerClass. (A stuck bit 0 is research row 2 of
  docs/research/gen1-glitches-2026-11-15.md; so the bit alone cannot tell "engaged" from "stuck": an EDGE (0 -> 1) can.)
- `wIsInBattle` (0xD057, verified: 0 none, 1 wild, 2 trainer) becomes 2 once the fight starts.
- Engagement requires: the trainer not already beaten (trainers.asm:272-277), the player on the trainer's row or column in the direction it FACES, within the trainer's
  view range (`wTrainerEngageDistance`), and the player in front of the sprite (`CheckPlayerIsInFrontOfSprite`, trainer_sight.asm:293-349).
- Sprite tables (repo facts, already used by `src/pokeagent/explorer/anomaly_sprites.py`): wSpriteStateData1 at 0xC100, 16 bytes per slot, slot 0 is the player,
  +0 picture id, +2 image index (0xFF = hidden), +9 facing direction (0 down, 4 up, 8 left, 0xC right; `ram_map.json` `wSpritePlayerStateData1FacingDirection` note).
  wSpriteStateData2 at 0xC200: +4 map Y plus 4, +5 map X plus 4 (map tile = byte minus 4). wMapSpriteExtraData at 0xD504, 2 bytes per sprite, read by EngageMapTrainer as
  `(slot - 1) * 2`: byte 0 = trainer class (200 and up for a trainer: OPP_ID_OFFSET), byte 1 = trainer set. Player position: `RAM_MAP["player_x"]` / `["player_y"]`.
- The Signals dataclass in `src/pokeagent/glitch_signals.py` already carries `misc_flags`, `in_battle`, `engaged_class`, `engaged_set`; `Signals.as_tuple()` is stored in
  snapshots: DO NOT change its field order or count.

## 3. Scope (exact files, in order)

Edit:
1. `src/pokeagent/glitch_signals.py`: add `MISC_SEEN_BY_TRAINER = 0x01`, `engaged_now(sig) -> bool`, `engagement_edge(prev, cur) -> str | None` (4.A). Nothing else in the file changes.
2. `src/pokeagent/glitchlab/trainer_escape.py`: `read_probe` adds keys `seen_by_trainer` and `engaged`; `verdict` adds key `seen_at_exclaim` and replaces the
   `engaged_class` note (4.B).
3. `src/pokeagent/glitchlab/survey.py` and `tools/glitch_probe.py` (the `survey` subcommand only): the position/facing-aware survey (4.C).
New:
4. `src/pokeagent/glitchlab/sprites.py`: `TrainerSprite`, `read_trainer_sprites(emu)` (4.C).
Tests (edit the three that encode the old model, add two):
5. `tests/test_glitch_signals.py` (add), `tests/test_glitchlab_trainer_escape.py` (adjust), `tests/test_glitchlab_survey.py` (rewrite for the new model),
   `tests/test_glitchlab_sprites.py` (new), `tests/test_glitch_probe_tool.py` (adjust the survey call only).
Keep every module under about 150 lines, one job each.

## 4. The work

### A. Signal functions (glitch_signals.py)
- `engaged_now(sig: Signals) -> bool`: `not sig.in_battle and bool(sig.misc_flags & MISC_SEEN_BY_TRAINER)`. It NEVER reads `engaged_class` or `engaged_set`.
- `engagement_edge(prev: Signals, cur: Signals) -> str | None`: `"seen"` when `prev.misc_flags & 1 == 0` and `cur.misc_flags & 1` and `not cur.in_battle`;
  `"battle"` when `not prev.in_battle and cur.in_battle` (Signals stores `in_battle` as a bool, so this cannot tell wild from trainer; that is fine here); `None` otherwise. A bit stuck at 1 across both samples yields `None` (no edge).
- Docstrings say plainly: `engaged_class` is a stale last-engaged byte, nonzero without engagement (real-ROM 2026-11-19); `engaged_now` cannot tell stuck from engaged,
  `engagement_edge` can.

### B. The probe rows (trainer_escape.py)
- `read_probe` adds `"seen_by_trainer": bool(sig.misc_flags & MISC_SEEN_BY_TRAINER)` and `"engaged": engaged_now(sig)`; existing keys stay (including `engaged_class`, now
  documented as log-only).
- `verdict` adds `"seen_at_exclaim": <the at_exclaim row's seen_by_trainer, or None if absent>`; the note `at_exclaim engaged_class=...` becomes
  `at_exclaim engaged_class=N (stale byte, log only)` and a new note `at_exclaim seen_by_trainer=B`. Existing verdict keys keep their meaning.

### C. The survey (sprites.py, survey.py, glitch_probe.py)
`read_trainer_sprites(emu) -> list[TrainerSprite]` (frozen dataclass: `slot, cls, trainer_set, x, y, facing`): slots 1..15; skip a slot whose picture id is 0 or image index is 0xFF;
a sprite is a trainer iff its wMapSpriteExtraData class byte is `>= TRAINER_CLASS_MIN = 200`; `x, y` are map tiles (byte minus 4); `facing` is `"down"|"up"|"left"|"right"` from the raw
0/4/8/0xC (any other raw value -> `None`, and such a sprite is returned with `facing=None`). Item-ball and ordinary NPC sprites (class byte under 200) are NOT returned.
`survey_map(emu_factory, state, map_id, kb, *, out_dir, menu_probe=None, name=None, max_steps=12)`: the `kb` and `distances` parameters are kept only for call compatibility
(`kb` may be None and is used only to label a sprite's class name by matching x,y; the survey no longer needs it). For each trainer sprite read from a fresh scratch copy:
1. Compute whether the player is on the trainer's sight line: same column for facing up/down (player on the facing side), same row for left/right. Not on it ->
   one row with `"reason": "off_line"`, NO presses, and move on. The survey does NOT navigate; it measures from a start state that already stands on the line. Say so in the report.
2. Otherwise walk toward the trainer one tile per step (press the button pointing at the trainer: facing down means the player is below it, so UP; and so on), up to `max_steps`
   or until adjacent. After each press, read `read_signals` and the player's x,y: a row per tile with `dist` (tiles between player and trainer), `player_x`, `player_y`,
   `seen_by_trainer`, `engaged` (`engaged_now`), `edge` (`engagement_edge` against the previous row, `None` on the first), `in_battle`, `misc_flags`, `status5`, `start_opened`.
   Stop at the first `edge` (the engine takes the player's control away). If the player's x,y did not change after a move, stop with `"reason": "blocked"`.
3. If the walk ends adjacent with no edge, press START once and record `start_opened` on that last row (the old "start_before_engage" measurement), then stop.
Per-trainer summary: `{"slot", "class", "x", "y", "facing", "engage_dist": <dist at the first edge or None>, "start_before_engage": <Start opened on a tile where engaged was False>,
"reason": None|"off_line"|"blocked"}`. Top-level summary keeps `map`, `report`, `runs`, `trainers`, `aborted` ("cap" beyond `MAX_RUNS = 60`).
Write rows with `scratch.report_path` exactly as today (under `<runs_dir>/discoveries/`). `tools/glitch_probe.py survey` keeps its flags; update the call.
Still buttons and RAM reads only, no writes, no GUI.

### D. Report, do not fix
In the Report section, state whether `active_reasons`'s `engaged_class == 0 and engaged_set == 0` clause should be dropped, with the evidence above. Do NOT edit `active_reasons`,
`glitch_guard`, or any detector: changing what blocks a checkpoint write is the controller's decision.

## 5. What NOT to do

- No ROM, no emulator run, no save state, no kb file. NEVER commit or publish a ROM, a save state or any ROM-derived data (`roms/`, `kb/`, `runs/` are gitignored; keep it so).
  Pokered symbol names and plain integers (addresses, the 200 class offset) are fine; no ROM bytes or hex dumps in code, docs, tests or logs.
- No RAM writes anywhere in `glitchlab/` or the tool (no `emu.write`, no `memory[...] =`). Buttons only.
- Do not change `Signals` fields or `as_tuple`, `active_reasons`, `glitch_guard`, the detectors, `ram_map.json`, `ram_symbols.py`, or the trainer-escape RECIPE.
- Do not add a navigation or pathfinding layer to the survey; off-line trainers are reported, not chased.
- Do not touch `src/pokeagent/explorer/` (the explorer's own trainer code and `SIGHT_GUESS` stay as they are).
- No new dependencies, no network, no GUI.

## 6. Verification

Baselines (run by the directive author on origin/main in a worktree, Python 3.12.12 via `uv run`, 2026-11-19):
```
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitch_signals.py tests/test_glitchlab_survey.py tests/test_glitchlab_trainer_escape.py tests/test_glitch_probe_tool.py
24 passed, 1 warning in 1.86s
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitchlab_script.py tests/test_glitch_probe_tool.py
11 passed, 1 warning in 0.97s
```
Full-suite baseline on origin/main in a fresh worktree without kb/ or roms/ (2026-11-19, `uv run pytest -q -p no:cacheprovider -rfEs`, serial, 5 minutes):
```
1 failed, 3451 passed, 73 skipped, 1 warning in 302.33s (0:05:02)
FAILED tests/test_lead_and_wild_switch.py::test_geodude_fight_pick_uses_the_real_kb_tables
  AssertionError: needs the gitignored kb/rom_tables.json (the laptop verify recipe copies it in)
```
That ONE failure is environmental (the gitignored ROM-derived kb is absent from a cloud worktree) and is the only failure allowed. Any other failure, or any new one, means stop and report it; do not mark done.
The controller's verify lane runs with the kb present and requires 0 failed there.
Synthetic tests (fixtures built in code: `FakeEmulator(memory)` from `src/pokeagent/emulator.py` with `.set(addr, val)`; subclass it to move a fake player on each `press`):
- `test_glitch_signals.py`: `engaged_now(Signals())` is False; `Signals(misc_flags=1)` True; `Signals(misc_flags=1, in_battle=True)` False; the REGRESSION cases
  `Signals(engaged_class=21)`, `Signals(engaged_class=14)`, `Signals(engaged_class=230)` are all NOT engaged (the real-ROM artifact); `engagement_edge` returns `"seen"` for
  (misc 0 -> 1, out of battle), `"battle"` for (not in battle -> in battle), `None` for a bit stuck at 1 on both samples and for 0 -> 0.
- `test_glitchlab_sprites.py`: a FakeEmulator memory with slot 1 a trainer (class byte 201, facing 0 = down, map tile (10, 8) so raw bytes 14 and 12), slot 2 an item ball (class byte
  21: NOT returned), slot 3 hidden (image index 0xFF: NOT returned), slot 4 a trainer with raw facing 7 (returned with `facing=None`); assert the returned list and the tile math.
- `test_glitchlab_survey.py`: (1) NO trainer on the map and `engaged_class` preset to 21 in RAM -> `trainers == []`, no row has `engaged` True (the stale-byte case);
  (2) one trainer facing down at (10, 8), player 6 tiles below on its column, fake sets wMiscFlags bit 0 when the player is within 3 tiles -> `engage_dist == 3`, the row at
  distance 4 has `engaged` False and `edge` None, the row at 3 has `engaged` True and `edge == "seen"`, and the walk stops there (no more presses); (3) the same trainer with the
  player on a different column -> `reason == "off_line"` and zero presses; (4) a fake wall (player x,y unchanged after UP) -> `reason == "blocked"`; (5) a trainer that never engages
  -> the walk ends adjacent, START is pressed once, `start_before_engage` True iff the menu probe says the Start menu opened with `engaged` False; (6) the `MAX_RUNS` cap.
- `test_glitchlab_trainer_escape.py`: `read_probe` returns `seen_by_trainer`/`engaged` correctly for misc_flags 1 and 0 and ignores a preset `engaged_class`; `verdict` returns
  `seen_at_exclaim` and the new notes; existing verdict assertions still pass.
- `test_glitch_probe_tool.py`: the survey subcommand still writes under `discoveries`, leaves the input state byte-identical, and exits 2 for a source under `checkpoints/`.
Each new test must fail on origin/main without the change. Commands, in order:
```
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitch_signals.py tests/test_glitchlab_sprites.py tests/test_glitchlab_survey.py
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitchlab_trainer_escape.py tests/test_glitch_probe_tool.py tests/test_glitchlab_script.py tests/test_glitch_guard.py
uv run pytest -q -p no:cacheprovider -rfEs
```
The last is the full suite, serial (xdist is NOT installed), about 5 minutes. Expected: exactly the baseline's one environmental failure and nothing else. Paste the final summary line.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call needing confirmation is rejected and the run ends mid-task. Never require an install, download or fetch. Never read outside the working directory.
- Use `uv run` (Python 3.12), never bare `python`. Serial tests, focused files first, `-p no:cacheprovider`.
- Do not search, glob or hunt for missing files: if something this directive names is missing, stop and write why in the Status row.
- Create no scratch or debug files; if one is unavoidable it goes under `.devin-scratch/` and stays (deleting is denied in the sandbox).
- If a tool call is genuinely blocked, stop and write why in the Status row rather than trying another way around it.
- Branch `directive/pokeagent-glitch-engagement-signal` only. Commit there as you go. Never commit to main, never push, never deploy; only the controller merges.
- Every commit message ends with this trailer line (docs/STANDARDS.md requires it for unsigned commits; the PR #331 gate flagged its absence):
  `Unsigned-Reason: automation without a key; Robert approved agent commits`
- Do not add a `## Queue` block. Free models only where model configuration is touched (it is not here).

## 8. Completion criteria, controller validation, Report

Done (Devin) means ALL of: the three focused commands above show 0 failed; the full suite shows only the baseline's one environmental failure; the synthetic tests in section 6 exist and prove BOTH directions
("no trainer -> not engaged" including the stale `engaged_class` case, and "engaged -> engaged" with `edge == "seen"`); `Signals.as_tuple` unchanged; every commit carries the
Unsigned-Reason trailer; nothing under `roms/`, `runs/`, `kb/` staged. Status row: `Review`, one line: tests added, full-suite tail.

Controller step after merge (NOT Devin, needs the ROM, laptop or Home Tower; listed so the result is checked on the real game):
1. `uv run python tools/glitch_probe.py survey --state runs/checkpoints/nugget_bridge.state --map 0x24 --name sig-r25` : expect every trainer row `engaged` False and
   `misc_flags` 0 even though RAM `engaged_class` reads 21 (all Route 25 trainers are beaten). A True here means the signal is still wrong.
2. With the directive-3 start state (an unbeaten Route 24/25 or Route 6 trainer): the same command; expect `edge == "seen"` on the tile where the trainer spots the player,
   then `in_battle` becoming 2. Record `engage_dist` against that trainer's real view range.
Report (findings first): (1) the signal chosen and why `engaged_class` was rejected, (2) the answer to the `active_reasons` question in 4.D, (3) test tails (focused and full),
(4) the commit sha, (5) anything in the pasted pokered source that contradicted section 2d.
