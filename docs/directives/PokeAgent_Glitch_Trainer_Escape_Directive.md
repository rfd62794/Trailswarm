# PokeAgent Glitch Exploration, Slice 2: Trainer-Escape ("Mew") Probe

Repo: PokeAgent. Branch: `directive/pokeagent-glitch-trainer-escape`. Depends on slice 1
(the PokeAgent Glitch Detectors directive, branch `directive/pokeagent-glitch-detectors`): this slice REUSES
the slice 1 module glitch_signals in the pokeagent package (`read_signals`, `Signals`, `active_reasons`, the address constants). If that module is not on
the branch you start from (`git log --oneline -3` and look for the glitch_signals module), STOP and write "slice 1 not
merged" in the Status row. Do not recreate it and do not re-read its bytes by hand.

## 1. Why this exists

`docs/research/gen1-glitches-2026-11-15.md` rows 2, 3, 5 and sections 4 (items 1, 6, 7) and 5 describe the trainer escape and the
"Mew trick" as HYPOTHESES from wiki text; none of it is confirmed on our ROM. This slice builds a scripted, save-state-driven
probe so the controller can CONFIRM OR REFUTE each step on the laptop. The probe observes and records; it never rewards, steers,
or feeds a curriculum. Hypotheses to test (all UNVERIFIED until a real run shows them):
- H1: a long-range trainer spots the player; opening Start before the "!" resolves, then escaping (Teleport or Fly), leaves
  trainer-engagement state stuck (`wMiscFlags` bit 0, `wStatusFlags5` bit 0, `wEngagedTrainerClass`/`Set` nonzero, Start disabled).
- H2: a later fight against a Pokemon whose Special stat equals a species index leaves that value stale in the enemy block; on
  return to the escaped trainer's map an instant battle starts whose species derives from the stale Special (Mew = index 21 is
  the folk claim; the classic setup is a Route 25 Youngster's Slowpoke) and whose level derives from another stale byte.
H2 is the folk "Mew trick"; research row 5 marks it H (hypothesis). The probe records the stale Special, the encounter species
and level, and lets the controller compare them. It never injects a value (no RAM writes at all, see section 5).

## 2. Read first (all exist on main once slice 1 is merged)

- `AGENTS.md` (verify command, Python 3.12 via `uv run`)
- `docs/research/gen1-glitches-2026-11-15.md` rows 2, 3, 5; sections 4 (items 1, 6, 7), 5 (Rules)
- the glitch_signals module of slice 1 (read-only reuse)
- `src/pokeagent/emulator.py`: `Button` (line 18, values UP DOWN LEFT RIGHT A B START SELECT NONE), the `Emulator` Protocol
  (line 33), `PyBoyEmulator.press(button, hold_frames=8, settle_frames=16)` (line 104), `.tick(frames)` (115), `.read`/`.read_range`
  (118/121), `.save_state`/`.load_state` (156/160), `.close()` (166, `stop(save=False)`, so no SRAM is written),
  `FakeEmulator(memory)` (216: `.set(addr, val)`, `.presses` list, `.frames`, `.save_state` writes JSON of memory, `.load_state` reads it)
- `tools/explore_headless.py` lines 38-45: the boot idiom `emu = PyBoyEmulator(Path(rom), headless=True); emu.tick(60);
  emu.load_state(Path(state)); emu.tick(30)`; `tools/probe_buttons.py` is a small tool to copy the CLI shape from
  (`sys.path.insert(0, .../src)`, `--rom` default `os.environ.get("POKEAGENT_ROM", "roms/Pokemon Red.gb")`, `--state`, `--runs-dir`)
- `src/pokeagent/explorer/party_menu.py` lines 40-41: `is_start_menu(text)`, `menu_open(text)`; `screen_lines(tilemap_bytes)`
  (line 20) turns the 360-byte tile map into text. The tile map is read from 0xC3A0, length 360 (`src/pokeagent/explorer/perceive.py` line 13: `TILEMAP, TILEMAP_LEN`).
  Docstring there says the Start-menu texts were verified on the ROM 2026-11-05.
- `src/pokeagent/knowledge/trainers.py` line 35: `trainers_on(map_id, kb=None) -> [{"class", "party", "x", "y", "mons"}]`. Rows carry NO
  facing and NO sight range. `src/pokeagent/explorer/trainer_route.py` line 18: `SIGHT_GUESS = 4` is an UNVERIFIED guess (4 tiles, four directions).
  The kb behind it is the kb rom-tables JSON file (gitignored, ROM-derived): tests pass a hand-written `kb` dict
  (`{"map_trainers": {"<map id>": [{"class": "YOUNGSTER", "party": 1, "x": 10, "y": 8}]}, "trainers": {}}`) and never need it.
- `src/pokeagent/novelty/discoveries.py` line 15 (`DIR_NAME, LOG_NAME, STATE_SUFFIX = "discoveries", "discoveries.jsonl", ".discovery.state"`),
  line 39 `is_discovery_state(path)`: true for any file named `*.discovery.state` or under a directory named `discoveries`. That is
  the guard that keeps experiment states away from curriculum code. Every file this slice saves must satisfy it.
- `src/pokeagent/procedures/schema.py` and `src/pokeagent/explorer/behaviours/procedure_runner.py`: the existing "procedure" machinery
  (`Step` with `pre`/`action`/`effect`; `MAX_SCRIPT = 40` presses per `buttons` action). It is wired to the explorer `ctx`
  (one press per behaviour call, graded, stored under runs/procedures) and is NOT a standalone scripted-input API. Do NOT use or edit it.
  A small standalone runner is part of this slice (section 4.A); borrow only the idea.
- `tests/test_novelty.py` (style: `FakeEmulator`, `tmp_path`; tools are loaded in tests with
  `importlib.util.spec_from_file_location(name, TOOLS / "x.py")`, line 30-35)

## 3. Scope (exact files, in order)

New files:
1. `src/pokeagent/glitchlab/__init__.py` (docstring only)
2. `src/pokeagent/glitchlab/scratch.py`: `scratch_copy(state, scratch_root) -> Path`, `report_path(runs_dir, name) -> Path`
3. `src/pokeagent/glitchlab/script.py`: step schema, `load_script`, `run_script`, `Trace` rows
4. `src/pokeagent/glitchlab/trainer_escape.py`: `RECIPE` (data), `read_probe(emu)`, `verdict(rows) -> dict`, `run_recipe(...)`
5. `src/pokeagent/glitchlab/survey.py`: `survey_map(...)` trainer survey (4.C)
6. `tools/glitch_probe.py`: CLI with subcommands `repro` and `survey`
7. `tests/test_glitchlab_script.py`, 8. `tests/test_glitchlab_trainer_escape.py`, 9. `tests/test_glitchlab_survey.py`,
   10. `tests/test_glitch_probe_tool.py`
No existing file is edited. Keep every module small (one job each, under about 150 lines).

## 4. The work

### A. Standalone step runner (script.py) - the repo has no such API, so this slice adds it
A script is a list of steps loaded from plain data (a list of dicts, so it can live in JSON; `load_script(list) -> list[Step]`,
reject unknown keys and unknown buttons with `ValueError`). Step kinds:
- `{"id": "...", "press": ["RIGHT","RIGHT"], "hold": 8, "settle": 16}`: presses `Button[...]` in order via `emu.press`.
  Names are the `Button` members; `NONE` allowed. Cap `MAX_PRESSES_PER_STEP = 40`.
- `{"id": "...", "wait": 60}`: `emu.tick(n)`; cap 3000 frames per step.
- `{"id": "...", "mark": true}`: no input; just a trace row (used for "before spot", "at !", and so on).
- `{"id": "...", "until": {"addr": "0xD057", "equals": 2}, "press": ["NONE"], "max_presses": 30}`: repeat the press until the
  byte matches or the cap is hit; the row records `reached: true/false`. (`until` bytes are read with `emu.read`; no other predicate language.)
`run_script(emu, steps, probes, *, record) -> list[dict]`: after EVERY step read `probes` (a callable `emu -> dict`) and append one
row `{"i": n, "id": step.id, "frames": <emu frames if available else None>, "presses": <count so far>, "ram": <probes dict>,
"reached": bool|None}`. A total budget `MAX_TOTAL_PRESSES = 400` ends the run with `aborted: "budget"` as its last row.
Never writes memory: no `emu.write`, no direct PyBoy memory access anywhere in `glitchlab/`.

### B. Repro recipe (trainer_escape.py)
`RECIPE` is a module-level list of step dicts (DATA, not branching code) with these ids in order: `before_spot`, `walk_to_sight`,
`at_exclaim`, `start_menu`, `escape` (the presses that use Teleport: START, move to POKeMON, pick the Abra, pick TELEPORT; the exact
cursor presses depend on the party, so they are PLACEHOLDERS the controller edits: mark each placeholder step `"placeholder": true`
and have `run_recipe` refuse to run while any placeholder remains unless `--allow-placeholder` is passed), `after_escape`,
`special_fight` (fight the Special-setting Pokemon), `return_walk`, `on_return`. Because the cursor and walking presses depend on the
save, the CLI accepts `--script path.json` to replace the default `RECIPE`; the default only has to load and validate.
`read_probe(emu) -> dict` reads, per step:
- via slice 1: `read_signals(emu)` fields `misc_flags`, `status5`, `engaged_class`, `engaged_set`, `in_battle`, plus
  `active_reasons(...)` as a list of strings. Import the slice 1 constants; never respell those addresses.
- map and position: `wCurMap` 0xD35E, `wYCoord` 0xD361, `wXCoord` 0xD362 (read through `pokeagent.ram.RAM_MAP` keys `map_id`,
  `player_y`, `player_x`).
- enemy block: `wEnemyMonSpecies` 0xCFE5, `wEnemyMonLevel` 0xCFF3, `wEnemyMonSpecial` 0xCFFC (2 bytes; record `special_u16`
  big-endian and `special_lo`, the second byte), `wCurOpponent` 0xD059, `wTrainerClass` 0xD031.
- `wCurEnemyLevel` 0xD127, `wEnemyMonUnmodifiedSpecial` 0xCD2C, `wEnemyMonUnmodifiedLevel` 0xCD23 (UNVERIFIED candidates for
  "the other stale stat": log only, include them in every row so the controller can see which one the level follows).
- `start_menu_open`: `is_start_menu` of `screen_lines(emu.read_range(0xC3A0, 360))`; wrapped in try/except returning `None`
  (tests inject a fake `menu_probe` callable instead of building tile bytes).
`verdict(rows) -> dict` is a PURE function of the rows, with exactly these keys:
- `start_opened_before_engagement`: true iff the `start_menu` row has `start_menu_open` True (the Start menu really opened); `None` when that value is unknown. The row `at_exclaim` is also reported raw (`engaged_class` there) so the controller can see whether Start came before engagement.
- `trainer_state_stuck`: true iff, on row `after_escape`, `in_battle` is false AND (`misc_flags & 1` or `status5 & 1`) AND the map id differs from the `before_spot` row's map. The bit meanings are UNVERIFIED; the verdict also returns the raw bytes so the controller judges.
- `enemy_special`: the `special_u16`/`special_lo` seen on row `special_fight` (None if no row).
- `instant_encounter`: `{"species": .., "level": .., "map": ..}` from row `on_return` when `in_battle != 0` there and the `return_walk` row was not in battle; else `None`.
- `species_matches_special`: `instant_encounter.species == enemy_special.special_lo` (the folk claim); `None` when either is absent.
- `notes`: list of strings, including "bit meanings UNVERIFIED" always.
Never claim confirmation: the verdict is data. Output is a JSONL report (section 4.D).

### C. Trainer survey (survey.py)
`survey_map(emu_factory, state, map_id, kb, *, distances=(2,3,4,5,6), approach_presses=..., out_dir, menu_probe=None)`: for each
trainer in `trainers_on(map_id, kb)` and each distance d, from a fresh `scratch_copy` of the state, run a scripted approach that
ends with START pressed on the step the trainer is expected to spot the player. The approach is expressed as step dicts built from
data (a `approach_steps(trainer, d, direction)` function that returns press lists; the repo has NO sight range, so the survey
is a measurement of sight range, not an assumption: the walk goes tile by tile from d to 1 and the report records, per tile, whether
`engaged_class` became nonzero and whether `start_menu_open` was True). Each (trainer, d, tile) is one JSONL row:
`{"map", "trainer_idx", "class", "x", "y", "dist", "start_opened", "engaged", "misc_flags", "status5"}`. Summarise per trainer
`max_engage_dist` (largest d at which engagement began) and `start_before_engage` (Start opened while `engaged_class == 0`).
`emu_factory` is a callable returning an emulator already booted from a state copy (the CLI builds a `PyBoyEmulator`; tests build a
`FakeEmulator` with a scripted RAM timeline). A cap of `MAX_RUNS = 60` per call; stop and report `aborted: "cap"` beyond it.

### D. Output and safety (scratch.py)
- `scratch_copy(state, scratch_root)`: copies the given state file into `<scratch_root>/<name>.scratch.state` and returns the copy;
  the ORIGINAL is never opened for writing. Refuse (ValueError) when `scratch_root` is, or is inside, a directory named
  `checkpoints`, `leg_states`, `states`, or `baselines`, or when the source is a `*.discovery.state` copy-back (no daisy chains).
- `report_path(runs_dir, name)`: returns `<runs_dir>/discoveries/glitchlab-<name>.jsonl`; the path must satisfy
  `novelty.discoveries.is_discovery_state` OR be a `.jsonl` inside the `discoveries` directory (assert it in code and in a test).
  Any save state the probe wants to keep (for example at the instant encounter) is written ONLY as
  `<runs_dir>/discoveries/glitchlab-<name>-<row id>.discovery.state` with `emu.save_state` (never a checkpoint name).
- Tools use `--runs-dir runs` by default; tests pass `tmp_path`. No SRAM or save file is written; the emulator is closed with
  `close()` (it stops with `save=False`). Headless only: `PyBoyEmulator(Path(rom), headless=True)`. No GUI, no window, no input to the desktop.

### E. CLI (tools/glitch_probe.py)
`uv run python tools/glitch_probe.py repro --state S [--rom R] [--script path.json] [--allow-placeholder] [--runs-dir runs] [--name N]`
`uv run python tools/glitch_probe.py survey --state S --map ID [--rom R] [--runs-dir runs] [--name N]`
`main(argv=None) -> int`; prints one JSON summary line (the verdict, or the survey summary) and the report path; exit 0 on a clean
run, 2 on a usage error (missing state, bad script, placeholder), 1 on `aborted`. Importing the module must not start an emulator
(tests call `main` with an injected `emu_factory`/monkeypatched `PyBoyEmulator`).

### F. Addresses (Devin cannot browse; use exactly these)
Status VERIFIED = the name AND address are in `src/pokeagent/data/ram_map.json` with `"verified": true` (pret symbol). SYM = in
`ram_map.json` as a pret symbol with `"verified": false` (name known, not replay-confirmed). UNVERIFIED = no repo fact; log-only.
| Address | Symbol | Status |
|---|---|---|
| 0xD35E / 0xD361 / 0xD362 | wCurMap / wYCoord / wXCoord | VERIFIED |
| 0xD057 | wIsInBattle (0 none, 1 wild, 2 trainer; `ram_symbols.IS_IN_BATTLE`) | VERIFIED |
| 0xD059 / 0xD031 | wCurOpponent / wTrainerClass | VERIFIED |
| 0xCFE5 / 0xCFF3 | wEnemyMonSpecies / wEnemyMonLevel | VERIFIED |
| 0xCFFC (2 bytes) | wEnemyMonSpecial | VERIFIED (address and size); its use as a species seed is H2, UNVERIFIED |
| 0xCD2D / 0xCD2E | wEngagedTrainerClass / wEngagedTrainerSet (0xCD2E is also wEnemyMonStatMods: read only when not in battle; slice 1 already does) | SYM |
| 0xCD60 / 0xD730 | wMiscFlags / wStatusFlags5 (bit 0 of each = "trainer stuck" comes from research row 2 only) | SYM, bit meanings UNVERIFIED |
| 0xCD2C / 0xCD23 / 0xD127 | wEnemyMonUnmodifiedSpecial / wEnemyMonUnmodifiedLevel / wCurEnemyLevel | SYM; being "the other stale stat" is UNVERIFIED |
| 0xC3A0 (360 bytes) | tile map (`src/pokeagent/explorer/perceive.py` line 13) | VERIFIED by the repo's menu reader (docstring 2026-11-05) |
Do not read or add any other address. The Mew value (species index 21 = 0x15) and Slowpoke, Abra, Route 24/25 are controller
background from general knowledge: they appear only in prose and in the test data as plain integers, never as a ROM table.

## 5. What NOT to do

- No RAM writes at all: no `emu.write`, no `memory[...] =`, no poking a Special stat or a flag. The probe plays the game with
  buttons only. No arbitrary-code, Hall-of-Fame, name or Trainer-ID tricks. No ROM bytes or hex dumps in code, docs, tests or logs.
- Never write under `runs/checkpoints`, any leg-state or curriculum state directory, `baselines/`, or beside the input state.
- No edits to existing files (including `ram_symbols.py`, `ram_map.json`, `glitch_signals.py`, the research doc, other directives).
- Do not use the explorer engine, `ProcedureRunner`, the swarm, MCP servers, or the novelty tracker inside the probe.
- No new dependencies; no GUI; no network.

## 6. Verification

Synthetic tests only (`FakeEmulator`, `tmp_path`); no ROM. Each test fails on main without the change:
- `test_glitchlab_script.py`: `load_script` rejects an unknown key, an unknown button and an over-long press list; `run_script` on a
  `FakeEmulator` presses in order (`emu.presses`), emits one row per step with the probe dict, honours `until` (reached true then
  false at the cap), aborts with `budget`, and never calls `write` (wrap `write` to raise).
- `test_glitchlab_trainer_escape.py`: build row lists by hand (dicts) for (1) a full "stuck then instant Slowpoke-like encounter"
  timeline, (2) escape with no stuck bits, (3) stuck but no encounter on return, (4) encounter whose species differs from
  `special_lo`; assert each `verdict` key. `read_probe` on a `FakeEmulator` with the verified addresses returns the expected
  values (including `special_u16` from two bytes); a raising `menu_probe` gives `start_menu_open None`. `RECIPE` loads and
  validates; `run_recipe` refuses while a placeholder step remains.
- `test_glitchlab_survey.py`: a `FakeEmulator` timeline where trainer A engages at distance 4 and B at 2; assert the per-row
  fields, `max_engage_dist`, `start_before_engage`, and the `MAX_RUNS` cap.
- `test_glitch_probe_tool.py`: `main` with a tiny script file, injected factory and `tmp_path` runs dir: report file lands under
  `discoveries`, passes `is_discovery_state`-style path check, the input state file is byte-identical afterwards, no file is written
  under any directory named `checkpoints`; a source under `checkpoints/` is refused (exit 2).
Commands (only `uv run pytest ...` and `git`; others are refused):
```
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitchlab_script.py tests/test_glitchlab_trainer_escape.py
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitchlab_survey.py tests/test_glitch_probe_tool.py
uv run pytest -q -p no:cacheprovider -rfEs tests/test_novelty.py
uv run pytest -q -p no:cacheprovider -rfEs
```
The last is the full suite, serial (the xdist plugin is NOT installed), about 4 minutes, expected 0 failed. Paste the final summary
line in the Report. Any failure, including one that looks pre-existing, means stop and report it; do not mark done.

## 7. Rules for this run

- NON-INTERACTIVE: any confirmation prompt kills the run; choose the conservative option and note it.
- No installs, downloads or fetches. Never read outside the worktree. No scratch files except under `.devin-scratch/`.
- Do not search for or hunt for missing files: if a file this directive names is missing, stop and write why in the Status row.
- No ROM runs here (no `roms/` is available): nothing in this slice may need a ROM to pass its tests.
- Branch `directive/pokeagent-glitch-trainer-escape` only. Commit there as you go. Never commit to main, never push, never merge.
- Do not add a `## Queue` block. Cite only paths that exist on main, on the slice 1 branch, or are listed above as new files.

## Forbidden Actions

- Writing RAM, SRAM, save files or any ROM-derived data; committing states, ROMs, or runs output.
- Editing the protected-by-scope files named in section 5, or any file outside the ten new files.
- Running any real emulator, GUI or desktop input; pushing, merging, force-pushing, or touching main.
- Enforcing or "fixing" any UNVERIFIED bit meaning in other code; the probe only records.

## Required from User

The ROM-run part is the controller's, on the laptop with real states; Devin cannot do it. After merge the controller:
1. Provides a start state: an Abra that knows Teleport, standing near a candidate trainer (Routes 24/25 area), under the
   discoveries-adjacent scratch area, never a curriculum checkpoint.
2. Edits the placeholder presses in a `--script` JSON for the Teleport escape and the Special-setting fight, then runs
   `uv run python tools/glitch_probe.py repro --state <state> --script <json>` (headless) and reads the verdict and trace.
3. Runs `survey --map <id>` on Routes 24/25 and Viridian Forest to measure real sight ranges and Start-before-engage.
4. Decides from the traces whether H1/H2 hold, then marks the research doc rows. Nothing here is promoted before a real run.

## 8. Completion criteria and Report

Done when: the ten new files exist; every new test fails without the change and passes with it; the full suite shows 0 failed;
the probe contains no RAM write; output goes only to the discoveries area under runs/; `git status` is clean on the branch with
everything committed.

Report (in the Status row, findings first): (1) files added; (2) the verdict keys and one sample verdict from a test; (3) the
address table with any change you were forced to make; (4) full-suite summary line and per-file results; (5) branch head sha;
(6) anything UNVERIFIED you relied on; (7) open questions for Robert (see Decisions).

## Status
(unclaimed)

## Decisions taken for this slice (controller, 2026-11-15)

- The probe is observe-only with a button-driven script; it never writes RAM, even to "set up" the stale Special. If the folk
  setup cannot be reached by play alone, that is a finding, not a reason to poke memory.
- Standalone runner instead of the explorer procedure machinery: the latter needs an explorer ctx and stores under runs/procedures.
- Sight range is measured by the survey, not assumed from `SIGHT_GUESS`.
- Open for Robert: whether a confirmed H2 should ever feed a Mew-hunt goal (default: no, this stays research); whether a
  confirmed stuck-state signature should tighten the slice 1 guard.

<!-- new: src/pokeagent/glitchlab/__init__.py -->
<!-- new: src/pokeagent/glitchlab/scratch.py -->
<!-- new: src/pokeagent/glitchlab/script.py -->
<!-- new: src/pokeagent/glitchlab/trainer_escape.py -->
<!-- new: src/pokeagent/glitchlab/survey.py -->
<!-- new: tools/glitch_probe.py -->
<!-- new: tests/test_glitchlab_script.py -->
<!-- new: tests/test_glitchlab_trainer_escape.py -->
<!-- new: tests/test_glitchlab_survey.py -->
<!-- new: tests/test_glitch_probe_tool.py -->

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-pokeagent-glitch-trainer-escape-d-3f90ad |
| Base branch | - |
| Base commit | 855f59b66716f415236a29474e3543fc98516ca9 |

**Status log**
- 2026-11-15 21:00 · robert-claude-laptop · none → Queued
- 2026-11-16 07:22 · robert-claude-laptop · Queued → Approved
- 2026-11-16 07:22 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-pokeagent-glitch-trainer-escape-d-3f90ad; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7J4YWCSMSVFZN5MA0385ZJN
<!-- queue:end -->
