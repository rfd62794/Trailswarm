# Trailswarm: RAM trust tiers (assume pokered, verify over time) and a RAM-diff discovery tool for the unlabeled bytes

**Size:** L (three PRs are fine; see section 2). **Assignee:** devin.

**Depends on:** nothing open. Checked against origin/main 7bda1a9 (2026-11-12): `Party_View_Directive.md` is Done; `Party_View_Migration_Constants_Directive.md` (In progress) and `Party_View_Migration_Lead_Directive.md` (Queued) touch address constants and readers in `src/` but not `ram_map.json`, `ram_lookup.py`, `tools/build_ram_map.py` or `ramlab/`. `Measured_Ram_Address_Table_Directive.md` (Queued) creates `ramlab/observations.py`, `address_table.py`, `retro_vars.py` and `tools/ram_address_table.py`: this directive creates different files (`ramlab/trust.py`, `invariants.py`, `gaps.py`, `probe.py`, `games.py`, `tools/ram_recheck.py`, `tools/ram_probe.py`), so they can land in either order; do NOT build a per-game address table here, and do not touch those four files. `Event_Flags_And_Encounter_Table_Directive.md` (sibling) reads `trust` from this one but must not block on it.

**Read first (all in the worktree; if one is missing, stop and say so in the PR description; do not search):** `src/pokeagent/ram_lookup.py`, `tools/build_ram_map.py`, `tools/verify_ram.py`, `src/pokeagent/ramlab/labels.py`, `src/pokeagent/ramlab/findings.py`, `tests/test_ram_map.py`, `src/pokeagent/game/registry.py`, `src/pokeagent/game/spec.py`.

## 1. Why this exists

Robert, 2026-11-12: "It would be wiser to auto-assume the known addresses, while still verify over time, and focus some energy on the discovery of unmapped addresses, that also benefit our experiments, and other future experiments."

Today `src/pokeagent/data/ram_map.json` (one JSON object per line, inside a JSON array; 2,792 entries) has `verified: true` on only 121 of them, and the boolean reads as "do not use the other 2,671". That is the wrong default: every entry comes from pret/pokered's `pokered.sym` (symbols branch), which is correct for location. Measured 2026-11-12 (`uv run python`, counting the file):

```
entries 2792, verified 121, entries with a note 53
regions: sprites 875, party 638, battle 448, map 205, other 190, hram 168, menu 48, player 47,
         audio 43, scratch 43, link 30, event_flags 25, items 13, text 11, pokedex 8
encodings: u8 1923, bytes 843, bitmask 15, u16be 7, text 3, bcd 1
every entry: "source": "pokered.sym (pret/pokered, symbols branch)"
```

Real lines (fields are `name, addr, size, encoding, region, verified, source, sym`, plus optional `evidence`, `note`, `alias`):

```
{"name": "wPlayerMonNumber", "addr": "0xCC2F", "size": 1, "encoding": "u8", "region": "battle", "verified": true, "source": "pokered.sym (pret/pokered, symbols branch)", "sym": "wPlayerMonNumber", "note": "party index in battle", "evidence": "tests/rom/test_party_states.py::test_trainer_second_slot_active passed on the real ROM 2026-11-12"}
{"name": "wBattleMon", "addr": "0xD014", "size": 29, "encoding": "bytes", "region": "battle", "verified": true, ..., "evidence": "battle: wBattleMon mirrors party mon 1 (species, HP, level, moves, DVs, stats)", "note": "battle_struct (29 bytes): decode_battle_mon"}
{"name": "wGrassRate", "addr": "0xD887", "size": 1, "encoding": "u8", "region": "map", "verified": true, ..., "note": "encounter rate", "evidence": "Route 1: rate 25, 10 slots of ['PIDGEY', 'RATTATA'] L2-5"}
```

Two facts the boolean cannot say, both measured on the real ROM states in `tests/fixtures/rom_states/` (2026-11-12):
- `wBattleMon` is stale at battle start (species 0 while HP/level/PP hold leftovers) and `wPlayerMonNumber` is stale outside a battle: verified, but only valid in some states.
- `wGrassRate` 0xD887 and `wGrassMons` 0xD888 (20 bytes) keep the PREVIOUS map's slots when the current map has no grass. State `fainted_lead_overworld` (map 0x36, a gym) reads `wGrassRate = 0` while `wGrassMons` still holds `[3,165, 3,36, 4,36, 4,165, 5,36, 3,112, 2,165, 5,165, 4,112, 5,112]`. Valid only when the rate byte is nonzero.

And discovery. The bytes pokered does not name are where new knowledge lives. Computed 2026-11-12 from `ram_map.json` (WRAM 0xC000-0xDFFF = 8,192 bytes; an entry covers `[addr, addr+size)`):

```
bytes covered by some entry: 7,434 of 8,192
unlabeled bytes: 758 in 110 gaps; largest: 0xD430 (128 bytes), 0xC698 (80), 0xD66A (78), 0xCCA2 (48), 0xCC7A (29), 0xDFE2 (29)
entries whose size sits at the 256 cap (size is a guess, the label's true extent is unknown): 6
entries with an unknown-ish name (the regex in 3.3; the tool prints the current count, which differs by how the regex and the HRAM range are applied)
```

The 0xD430-0xD4AF gap is real: pokered.sym has `00:d42f wDestinationWarpID` and the next WRAM entry is `wNumSigns` at 0xD4B0 (`00:d4b0` in the sym). The "covered" figure is therefore an upper bound (inferred sizes). The tool in 4.3 must recompute these numbers and print them, so the next run can compare against this paragraph.

**What already exists (use it; building a second copy is the failure mode here).** The repo has a discovery pipeline: `src/pokeagent/explorer/ram_diff.py` (opt-in `--ram-diff` snapshots around presses of an explorer run), `src/pokeagent/ramlab/{mine,verify,labels,findings,flags,replay,headless,pipeline}.py`, `tools/ram_discover.py {mine,verify,report}` (ranks event-diff candidates, replay-verifies, writes `src/pokeagent/data/ram_findings.json`, and flips matching labels to verified), `tools/ram_seed.py`, `tools/verify_ram.py` + `tools/ram_checks.py` (hand-written ROM checks that flip `verified`). Those work from a full explorer run's records. They do NOT (a) read the unlabeled gaps as a thing, (b) take a short scripted sequence of labelled events from one state, (c) check sym-tier entries cheaply, or (d) record a tier. This directive adds exactly those four, as small modules, and reuses `LabelIndex`, `findings.upsert` and `ramlab.headless`'s emulator setup where they fit.

## 2. Scope (three PRs, in order; each stands alone and leaves the suite green)

**PR A. Trust tiers.**
1. `src/pokeagent/ramlab/trust.py` <!-- new: src/pokeagent/ramlab/trust.py --> (under 250 lines): `TIERS`, `tier_of(row)`, `validate(rows)`, `promote_verified(row, evidence)`.
2. `src/pokeagent/ram_lookup.py` (73 lines): `MapEntry.trust`, `is_usable`, tier shown by `describe`. Stay under 150 lines.
3. `tools/build_ram_map.py` (162 lines): carry `trust`; `--migrate-trust` mode that needs no sym file. Stay under 250.
4. `src/pokeagent/data/ram_map.json`: gains `trust` on every row (one-time migration) and the four caveat rows in 4.1.
5. `tests/test_ram_trust.py` <!-- new: tests/test_ram_trust.py -->, additions to `tests/test_ram_map.py`.

**PR B. Verify over time.**
6. `src/pokeagent/ramlab/invariants.py` <!-- new: src/pokeagent/ramlab/invariants.py --> (under 250): pure check functions over bytes.
7. `tools/ram_recheck.py` <!-- new: tools/ram_recheck.py --> (under 200): the CLI.
8. `tests/test_ram_invariants.py` <!-- new: tests/test_ram_invariants.py -->, `tests/rom/test_ram_recheck.py` <!-- new: tests/rom/test_ram_recheck.py -->.

**PR C. Discovery.**
9. `src/pokeagent/ramlab/games.py` <!-- new: src/pokeagent/ramlab/games.py --> (under 80): game key to map path.
10. `src/pokeagent/ramlab/gaps.py` <!-- new: src/pokeagent/ramlab/gaps.py --> (under 120): the unlabeled-gap computation.
11. `src/pokeagent/ramlab/probe.py` <!-- new: src/pokeagent/ramlab/probe.py --> (under 250): the labelled-event snapshot diff.
12. `tools/ram_probe.py` <!-- new: tools/ram_probe.py --> (under 200): `gaps`, `run`, `promote`.
13. `tests/test_ram_gaps.py`, `tests/test_ram_probe.py`, `tests/test_ram_games.py` (all <!-- new -->), `tests/rom/test_ram_probe_rom.py` <!-- new: tests/rom/test_ram_probe_rom.py -->.

No existing file may pass 600 lines; every new module stays under 250 (limits above).

## 3. The work

### 3.1 The `trust` field (PR A)

Each row gets `"trust"`, one of four strings:

| tier | meaning | usable by default |
|---|---|---|
| `sym` | a pokered label. Location assumed correct. Nothing has contradicted it. | yes |
| `verified` | a ROM state test or ramlab replay asserts it; `evidence` names which. | yes |
| `caveat` | known stale, or valid only in some states. `note` MUST contain a clause starting `valid when` (for example `valid when wIsInBattle != 0`). Never `verified` without that clause. | yes, but only under the note's condition |
| `discovered` | found by the probe tool; NOT in pokered. `evidence` names the probe run(s). `source` is `ram_probe <run id>`, not the sym string. | no; opt in with `is_usable(e, allow_discovered=True)` |

**`verified` stays a stored boolean (least invasive).** Reasons: `tests/test_ram_map.py::test_existing_verified_names_never_downgraded` and `test_verified_entries_carry_evidence`, `tools/verify_ram.py`, `tools/ram_discover.py`, `ramlab/labels.py` and `ramlab/findings.py` all read `verified` today; making it derived would change every one of them for no gain. Rules, enforced by `trust.validate(rows)` and a test over the real file:
- `trust == "verified"` iff `verified is True` and `evidence` non-empty, EXCEPT `caveat`: a caveat row keeps whatever `verified` it already had (so `wBattleMon` and `wPlayerMonNumber` stay `verified: true`, and the never-downgraded test keeps holding), and its `note` still carries `valid when`.
- `trust == "sym"` iff `verified` is false and no caveat. `discovered` rows have `verified: false` until a ROM test asserts them.
- A row with no `trust` key loads as `verified` when `verified` is true, else `sym` (so an old file still loads). `load_map` never writes.
- `validate` returns a list of problem strings; an unknown tier, a `caveat` without `valid when`, a `discovered` with no evidence, or `verified`/`trust` disagreeing is a problem.
- **Never downgraded:** a pure function `no_downgrade(prior_rows, new_rows)` returns the names whose tier went from `verified` or `caveat` to `sym`, or whose `verified` went true to false. The new test asserts `[]` on the file as loaded before the migration (build the prior rows in the test from the migrated rows with `trust` removed, plus the 121 `verified` flags) and on a hand-built downgrade case. Promotion goes only `sym -> verified` (and `discovered -> verified`); `promote_verified(row, evidence)` refuses an empty evidence string and refuses a `caveat` row.

`ram_lookup.py`: `MapEntry` gains `trust: str = "sym"`; `load_map` fills it (derivation above when the key is missing); `is_usable(e, *, allow_discovered=False) -> bool`; `describe` prints the tier where it printed `verified`/`unverified` (keep the word `verified` in the output for a verified row; `tests/test_ram_map.py::test_describe_reads_live_value` must pass unchanged).

`tools/build_ram_map.py`: `carry` must copy `trust` (it carries `verified` and `evidence` today; without this the next rebuild from a sym file would silently reset every tier). New flag `--migrate-trust`: reads the existing `ram_map.json` only (no sym file, so it runs in a Devin worktree), sets `trust` where absent by the derivation above, applies the four caveat rows below, validates, and rewrites in the existing format (`write_map`). Run it once and commit the result.

The four seed `caveat` rows (apply via `data/ram_overrides.json`, which `apply_overrides` already applies last (it uses `dict.update`, so a patch REPLACES each key it names), so a rebuild keeps them. Each patch therefore carries the FULL old `note` text followed by `; valid when ...`, and keeps the row's existing `verified`/`evidence`, adds `trust` and EXTENDS `note`, never replaces the layout text):

| name | addr | valid when (put in `note`) |
|---|---|---|
| `wBattleMon` | 0xD014 | `valid when wIsInBattle != 0 and wBattleMon species byte != 0` (stale at battle start: species 0, HP/level/PP leftovers) |
| `wPlayerMonNumber` | 0xCC2F | `valid when wIsInBattle != 0` (stale outside battle) |
| `wGrassRate` | 0xD887 | `valid when the byte is nonzero; zero means the current map has no grass table` |
| `wGrassMons` | 0xD888 | `valid when wGrassRate != 0; otherwise the previous map's slots remain` |

Keep the existing `note` text first, then `; valid when ...`. Do not add other caveat rows: an entry becomes a caveat only with a measured stale case pasted into its `evidence`.

### 3.2 Verify over time (PR B)

`ramlab/invariants.py` holds PURE checks (bytes in, result out; no emulator, so they test with synthetic bytes). A result is one of `ok`, `fail`, `skip` plus a reason string. Skip means the precondition was not met in that state (not a pass). The checks, each tied to the entries it covers by name pattern or encoding:

1. `bcd`: every nibble 0-9 (`wPlayerMoney`, 3 bytes, is the only bcd entry today).
2. `u16be_hp`: for an entry pair `<X>HP` / `<X>MaxHP` (`wPartyMon1HP`/`wPartyMon1MaxHP`, `wBattleMonHP`/`wBattleMonMaxHP`, `wEnemyMonHP`/`wEnemyMonMaxHP`): HP <= MaxHP and MaxHP in 1..999. Battle pairs skip unless `wIsInBattle != 0` and the struct species byte is nonzero.
3. `level_range`: a `...Level` u8 entry is in 1..100 (battle ones under the same battle precondition).
4. `party_list`: `wPartySpecies` (0xD164) is a list of `wPartyCount` bytes, each in 1..190, followed by 0xFF; `wPartyCount` (0xD163) is 0..6. For each slot i the species byte of `wPartyMon{i+1}` (0xD16B + 44*i) equals list[i].
5. `enemy_party_list`: same shape for `wEnemyPartyCount` 0xD89C / `wEnemyPartySpecies` 0xD89D, evaluated only when `wIsInBattle == 2`; otherwise skip.
6. `bag_list`: `wNumBagItems` 0xD31D is 0..20 and the byte after `2*count` bytes of `wBagItems` (0xD31E) is 0xFF.
7. `text_terminated`: a `text`-encoded entry that holds a name (`wPlayerName`, 11 bytes) contains a 0x50 terminator within its size.

No other entry is checked: an entry no invariant covers STAYS `sym`. A pass on an unrelated byte never promotes anything (no vacuous promotion). The invariant table is a plain dict `{check_id: (applies(entry) -> bool, fn)}`.

`tools/ram_recheck.py`:

```
uv run python tools/ram_recheck.py --rom "roms/Pokemon Red.gb" --states tests/fixtures/rom_states [--game pokemon-red] [--apply]
```

For each `*.state` it loads the state in `PyBoyEmulator(rom, headless=True)` (the loading pattern in `tests/rom/rom_helpers.py`: `emu.load_state(path); emu.tick(1)`), runs every applicable check, and prints one row per entry: ok-count / fail-count / skip-count over the states, plus any FAIL with state name and reason. Promotion rule: an entry is promoted `sym -> verified` only when it has at least 2 `ok` states, 0 `fail`, and `--apply` is given; evidence text is `invariant <check_id> held in N/N states (<names>) on <today>, tools/ram_recheck.py`. **It never demotes.** A `fail` changes nothing in the file: it prints `FAIL` and the tool exits 1 so the controller notices; the controller decides whether the entry becomes a `caveat`. Default (no `--apply`) is a dry run that writes nothing. Without the ROM (`--rom` path missing) it prints `skipped: no ROM` and exits 0. It is meant to be run by the controller on the laptop with the ROM, on any schedule; the tool takes no schedule.

### 3.3 Discovery (PR C)

**Game keying (`ramlab/games.py`).** The map is per memory family, not per game: Red and Blue share memory (`GameSpec.memory_family`; `LEGACY_FAMILY = "gen1-pokemon"` and Red owns `ram_map.json`). `map_path_for(game_key) -> Path`: `get_game(key)` from `pokeagent.game.registry` (raises KeyError naming the known games; let it), then `data/ram_map.json` when `spec.memory_family == LEGACY_FAMILY`, else `data/ram_map.<memory_family>.json`; when that file is missing raise `ValueError` that names the file and says to build it with `tools/build_ram_map.py` from that game's sym file. Today only `pokemon-red` is registered; Blue is NOT registered here (do not edit `registry.py`). The test registers a fake Blue-like spec by monkeypatching `registry.GAMES` (same family: same path as Red; another family: the `ram_map.<family>.json` path and the ValueError when absent). Every tool takes `--game` (default `pokemon-red`) and writes under `<out root>/ramprobe-<game>-<state stem>-<YYYYMMDD-HHMM>/` where `--out-root` defaults to `runs`; EVERY test (the FakeEmulator probe test and the ROM test) passes `tmp_path` as the out root and never writes the real `runs/`. Nothing in `probe.py` or `gaps.py` names Red, an address or a pokered label; the only Red-specific inputs are the map file and the ROM/state the caller passes.

**Gaps (`ramlab/gaps.py`).** `wram_gaps(entries, lo=0xC000, hi=0xDFFF) -> list[Gap]` where `Gap = (addr, length)`: maximal runs of bytes covered by no entry; `summary(entries) -> dict` returns `{covered, total, unlabeled, gaps, largest: [(addr, length) x6], at_cap: n, unknown_named: (count, bytes)}` (at_cap = entries with size 256; unknown_named = the regex `Unused|Unknown|Filler|Padding|Buffer|Scratch|Temp|Tmp`, case-insensitive). `tools/ram_probe.py gaps` prints it. The expected figures on the committed map are in section 1; if yours differ, say so in the report with both numbers. The sym file is gitignored and absent from a Devin worktree (`.devin-scratch/` is listed at line 8 of `.gitignore`; read the file with the Read tool if you need to see it), so the computation is from `ram_map.json`; if `--sym PATH` is given, ALSO parse it (format below) and report labels whose map entry has an inferred size, but never require it:

```
; File generated by rgblink
00:0000 NULL
00:d42f wDestinationWarpID
00:d4b0 wNumSigns
00:d747 wEventFlags
00:d887 wGrassRate
00:d887 wLinkEnemyTrainerName
00:d888 wGrassMons
```

(`bank:addr name`; WRAM is bank 00, 0xC000-0xDFFF; skip names containing `.` and `@`; several names can share an address.)

**Probe (`ramlab/probe.py`).** From ONE saved state, run a script of labelled events headlessly and diff WRAM around each:

```json
{"version": 1, "game": "pokemon-red", "idle_frames": 30, "repeat": 3,
 "events": [
   {"label": "step_up",   "presses": ["up"]},
   {"label": "open_menu", "presses": ["start"]},
   {"label": "close_menu","presses": ["b"]},
   {"label": "text_a",    "presses": ["a"], "settle": 60}
 ]}
```

For each event: snapshot `emu.read_range(0xC000, 0x2000)`; apply the presses (`emu.press(Button, hold_frames=8, settle_frames=...)`); snapshot again. **Noise control:** before the events, load the same state `repeat` times and tick `idle_frames` with no input, recording every byte that changes (the time-driven set); a byte is a result only if it changed in the event and is not in the noise set from the control runs. Each event runs from a freshly loaded state (so events are independent and the run is reproducible); `repeat` repeats each event and keeps only bytes that changed the same way in every repeat. For each surviving byte emit `{addr, before, after, label}` with `before`/`after` as ints. The report splits results into `unlabeled` (inside a gap from `gaps.py`) and `labelled` (inside an entry; counted only, not listed beyond the entry name), caps the listed unlabeled bytes at 200 per event, and writes `probe.json` (per-event lists, the noise set size, the gap summary, the state file name and `sha1` of the state file) plus `report.txt` under the `runs/ramprobe-...` directory. `runs/` is gitignored (`runs/` in `.gitignore`); never write outside it. Events that need a battle, an item pickup or a map change are expressed as a state that sits in front of the trigger plus the presses that fire it; the tool does not try to be clever.

**Promote (`tools/ram_probe.py promote`).**

```
uv run python tools/ram_probe.py promote --addr 0xD430 --size 1 --name wDisc_D430 --evidence-run runs/ramprobe-... --evidence-run runs/ramprobe-... [--region other] [--apply]
```

Writes a row with `trust: "discovered"`, `verified: false`, `source: "ram_probe <run ids>"`, `evidence` = the labels and `before->after` pairs seen in each run, `encoding: "u8"` or `"bytes"` by size. Refuses unless ALL hold: the address range lies wholly inside an unlabeled gap (never overlaps a pokered-labelled range); at least TWO distinct run directories show the byte changing under the same event label; the name is not already used; `--evidence-run` directories exist. Default is a dry run that prints the row; `--apply` edits `ram_map.json` (sorted like `build_ram_map.main`) and re-validates with `trust.validate`. It never touches an existing row. `ram_lookup.load_map` loads `discovered` rows like any other; `is_usable` withholds them by default.

## 4. What NOT to do

- **Never publish ROMs. No ROM bytes, no large dumps in the repo.** `probe.json` lists changed bytes only (addr, before, after) and lives under the gitignored `runs/`; do not commit anything from `runs/`. Do not copy `pokered.sym` into the repo or paste more than the seven sample lines above into a file (docs/LEGAL.md: labels derived from it are credited; the file itself is not redistributed).
- No network, no installs, no downloads. Do not fetch pokered or any other source.
- Do not run the emulator or look for a ROM: none exists in a Devin worktree, and the ROM-backed tests must SKIP cleanly. Do not search for `roms/`.
- Keep modules small: every new module under 250 lines; no existing file over 600; no file you touch may grow past its limit in section 2.
- Keep the layering allow-list rule: `tests/test_layers.py` (src must not import `tools/`) and `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size` (the explorer package imports only its allow-list of top-level modules). New code lives under `pokeagent.ramlab` and `tools/`; do NOT import `ramlab` from `src/pokeagent/explorer/`, and do not add to the explorer allow-list. `tools/*.py` may import from `pokeagent`; the reverse is forbidden.
- Use `uv run` only; never bare `python`. Python is 3.12.
- Do not downgrade anything: no `verified: true` becomes false, no tier moves down, in code or in data. Do not remove an `evidence` string. Do not touch `ram_names.json`.
- Do not rewrite `explorer/ram_diff.py`, `ramlab/mine.py`, `verify.py`, `labels.py`, `findings.py`, `tools/ram_discover.py`, `tools/verify_ram.py` or `tools/ram_checks.py`. Reuse their output formats; do not change them. Do not build the per-game address table (`Measured_Ram_Address_Table_Directive.md` owns it).
- Do not register Pokemon Blue or Yellow, and do not add game-specific addresses to `probe.py`/`gaps.py`.
- Do not change a test's expected value to make it pass; stop and say which test.
- No scratch or debug files outside `.devin-scratch/`; deleting is denied in the sandbox.

## 5. Verification (exact commands, from the worktree root)

Interpreter (confirmed on this branch 2026-11-12):

```
uv run python --version
```
Expected: `Python 3.12.12`.

Baseline on origin/main 7bda1a9 (real output, 2026-11-12) for the files this work touches or sits beside:

```
uv run pytest -q -p no:cacheprovider tests/test_ram_map.py tests/test_ramlab_flags.py tests/test_ramlab_mine.py tests/test_ramlab_verify.py tests/test_ramlab_report_rom.py tests/test_ram_diff.py tests/test_campaign.py tests/test_goal_order.py tests/test_false_goal_detectors.py tests/test_trainer_ledger.py tests/test_layers.py tests/rom
77 passed, 9 skipped, 1 warning in 2.39s
```

After PR A add `tests/test_ram_trust.py`; after B `tests/test_ram_invariants.py`; after C `tests/test_ram_gaps.py tests/test_ram_probe.py tests/test_ram_games.py`, and run the same command with those appended. Expected: zero failed, at least 9 skipped (the ROM ones, including the new `tests/rom/` files), no skip in the new non-ROM files.

Per-item checks (all non-ROM):

1. `uv run python tools/build_ram_map.py --migrate-trust` edits only `src/pokeagent/data/ram_map.json` and `src/pokeagent/data/ram_overrides.json` (check with `git status --short`). Then, in a test, `validate(load rows) == []`; counts: `verified+caveat` rows equal 121 (the caveat rows stay verified), the four caveat rows exist, `sym` count + `verified` count + `caveat` count == 2792 (before any discovered row).
2. Tier derivation: a row without `trust` loads as `verified` when `verified` is true and `sym` otherwise; `caveat` without `valid when` fails `validate`; `no_downgrade` flags a hand-built downgrade; `promote_verified` refuses empty evidence and refuses a caveat.
3. `carry`: a rebuild (`build.carry(entries, prior_rows_with_trust)`) keeps `trust`.
4. Invariants on synthetic bytes: each of the 7 checks has one ok, one fail, one skip case; a party of 2 with species list `[1, 4, 0xFF]` is ok, a count of 3 with that list is fail; an entry covered by no check stays `sym` after a recheck run with a fake emulator that returns plausible bytes; two ok states promote, one ok state does not, a fail blocks promotion and the tool exits 1 without editing the file.
5. Gaps: a synthetic map with known gaps returns them exactly (including a gap at 0xC000 and one ending at 0xDFFF, and overlapping entries); `summary` on the committed map prints the figures in section 1 (assert `unlabeled == 758` and `gaps == 110` only if your run reproduces them; otherwise report the numbers and assert the invariant `covered + unlabeled == 8192`).
6. Probe with `FakeEmulator`: a script where event `step_up` flips one gap byte and one labelled byte and a noise byte that also changes in the idle control: only the gap byte is listed under `unlabeled`, the labelled one is counted, the noise byte is dropped; a byte that changes in 2 of 3 repeats is dropped; the run directory is under `runs/ramprobe-<game>-...` and contains `probe.json` and `report.txt`.
7. Promote: refuses a range overlapping a labelled entry, refuses one run directory, refuses a duplicate name; accepts two run directories and, with `--apply`, writes a `discovered` row that passes `validate` and that `is_usable` withholds by default and allows with `allow_discovered=True`.
8. Games: red and a fake same-family Blue map to the same path; a fake other-family game maps to `ram_map.<family>.json` and raises `ValueError` while that file is absent.
9. ROM-backed tests (they must skip without the ROM, using the `rom_emu` fixture and `load` from `tests/rom/rom_helpers.py`): `tests/rom/test_ram_recheck.py` runs the checks over all six fixture states in dry-run and asserts zero `fail`; `tests/rom/test_ram_probe_rom.py` runs a one-event probe (`up` from `bedroom`) with the output root set to pytest `tmp_path` and asserts the run directory is written there. Expected locally: both SKIP. The controller runs them on the laptop.

```
git status --short
```
Expected: only the files named in section 2 (plus `ram_map.json` and `ram_overrides.json`).

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch and PR A, B and C all present on it (or three PRs each reaching Review).
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- No model-configuration changes (free models only applies; this work has none).
- If a tool call is genuinely blocked, stop and write why in the PR description rather than trying another way around it.

## 7. Completion criteria

- [ ] `validate()` returns `[]` on the migrated `ram_map.json`; 121 rows are `verified` or `caveat`; four named caveat rows carry `valid when`. <!-- test: tests/test_ram_trust.py -->
- [ ] `tests/test_ram_map.py` passes unchanged (never-downgraded and evidence rules still hold). <!-- test: tests/test_ram_map.py -->
- [ ] A rebuild keeps `trust` (`carry`). <!-- test: tests/test_ram_trust.py -->
- [ ] `ram_recheck.py` promotes only with 2+ ok states, never demotes, exits 1 on a fail, exits 0 with `skipped: no ROM`. <!-- test: tests/test_ram_invariants.py -->
- [ ] `ram_probe.py gaps` prints the gap summary; `run` writes under `runs/ramprobe-...`; `promote` refuses what 3.3 says it refuses. <!-- test: tests/test_ram_probe.py -->
- [ ] Keyed by game: Red and a fake Blue share the map path; no Red-specific code in `probe.py`/`gaps.py`. <!-- test: tests/test_ram_games.py -->
- [ ] The baseline command plus the new files: zero failed, ROM tests skipped, `test_layers.py` and the explorer layering test green.
- [ ] No ROM bytes, no dump, nothing from `runs/` committed; every new module under 250 lines; line counts of every touched file reported (the Read tool shows line numbers).

## 8. Report

Findings first: what was built per PR, the figures `gaps` printed (covered, unlabeled bytes, number of gaps, largest six, at-cap count) next to the figures in section 1, and the tier counts after migration. Then the tails of the baseline command before and after, `git status --short`, and line counts for each new and each touched file (from the Read tool). State plainly that no ROM was available and which tests skipped. Close with a short "the controller runs on the laptop" list: `uv run python tools/ram_recheck.py --rom "roms/Pokemon Red.gb" --states tests/fixtures/rom_states` (dry run, then `--apply`), the ROM tests in `tests/rom/`, and a first `tools/ram_probe.py run` over a script of step, menu open, menu close and text advance from `bedroom.state`, run twice, so `promote` has the two runs it needs.

## Required from User

Nothing for the build. After merge, Claude (controller) runs the recheck and the first probes on the laptop with the ROM and decides promotions of any `discovered` rows. Pokemon Blue and Yellow reuse this once a game spec and a sym file for them exist.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.
- Never publish, commit or print a ROM, a ROM-derived dump or a save-state dump.

## Sandbox needs

- Read(src/pokeagent/data/ram_map.json)
- Read(src/pokeagent/data/ram_overrides.json)
- Read(tests/rom/rom_helpers.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(uv run python tools/build_ram_map.py --migrate-trust)
- Exec(uv run python tools/ram_probe.py gaps)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-ram-trust-tiers-and-discovery-directive |
| Base branch | - |
| Base commit | 62489c33b40fa4e6e623b7841d7acda24a689c1e |

**Status log**
- 2026-11-12 15:56 · robert-claude-laptop · none → Queued — Robert 2026-11-12: auto-assume known addresses, verify over time, discover unmapped; merged via PR #212
- 2026-11-12 15:56 · robert-claude-laptop · Queued → Approved — lint override: Paths it cites under tools/ and src/pokeagent/ramlab that are not on main are new files this directive creates (Scope lists them as new).
- 2026-11-12 15:57 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-ram-trust-tiers-and-discovery-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M78RSFRBVYWNFD7WTFH17XQ1
- 2026-11-12 16:01 · dispatcher · launched pid=18396; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-ram-trust-tiers-and-discovery-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (8 declared need(s); 3 external))
<!-- queue:end -->
