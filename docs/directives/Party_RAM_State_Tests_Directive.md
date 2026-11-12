# Trailswarm: ROM-backed tests that pin party, battle, enemy-party and box RAM field by field against real saved states

**Size:** S. **Assignee:** devin.

**Depends on:** none. **Fixtures are already committed:** the six states are in `tests/fixtures/rom_states/` and `.gitattributes` exists at the repo root (both committed by Claude with this directive, before dispatch). The ROM is not in your worktree, so every ROM test skips: your run is skip-only, plus the no-ROM table test.

## 1. Why this exists

A read-only audit (2026-11-12) found that of 2,792 entries in `src/pokeagent/data/ram_map.json` only 107 are `"verified": true`, and none of the party/battle structs are pinned by a test against real game bytes: `wPlayerMonNumber`, `wPartyGainExpFlags`, `wPartyFoughtCurrentEnemyFlags`, `wEnemyPartyCount`, `wEnemyPartySpecies`, `wEnemyMons`, `wBoxCount`, `wBoxMons`, `wBoxMonOT`, `wBoxMonNicks` and `wEnemyMonPartyPos` are `verified: false`. The existing ROM tests (`tests/test_real_rom.py`, `tests/test_golden_red.py`) skip without the ROM and no test asserts a single party field. This directive writes the test file; the controller (Claude) runs it on the laptop with the ROM and then flips the verified flags.

Audit correction recorded here: `git ls-files baselines runs` lists nothing real. `baselines/` and `runs/` are gitignored (`.gitignore` lines 1-6). The only tracked `.state` files are 4-byte stubs under `tests/fixtures/review/runs/` and cannot load. So there are NO tracked real states: every state this test needs is a fixture the controller copies in (Required from User), and the test skips cleanly when a state is absent. Trainer-battle (`wIsInBattle` = 2) and box-holding states DO exist, untracked, and were probed by the controller on 2026-11-12; their values are pasted below.

## 2. Scope (one PR, in order)

1. `tests/rom/conftest.py` <!-- new: tests/rom/conftest.py --> : the `rom_emu` fixture; and `tests/rom/rom_helpers.py` <!-- new: tests/rom/rom_helpers.py --> : `ROM`, `STATES` and `load(...)`. (`tests/` has no `__init__.py`, so do not add one anywhere: pytest puts `tests/rom` on `sys.path`, and the test files import `from rom_helpers import load`.)
2. `tests/rom/test_party_states.py` <!-- new: tests/rom/test_party_states.py --> : the field-by-field assertions below; and `tests/rom/party_states_covered.py` <!-- new: tests/rom/party_states_covered.py --> : the `COVERED` table.
3. `tests/rom/test_party_states_table.py` <!-- new: tests/rom/test_party_states_table.py --> : no-ROM tests of the coverage table (these run in Devin's worktree).

4. `.gitattributes` already exists at the repo root (committed before dispatch) with `tests/fixtures/rom_states/*.state binary` and `*.state binary`. Do not edit it; check it is there.

No other file changes. Specifically `src/pokeagent/data/ram_map.json` is NOT edited by you (see 3.4).

## 3. The work

### 3.1 Skipping cleanly (this is how the file behaves in YOUR worktree)

`roms/` is gitignored, so `roms/Pokemon Red.gb` does not exist in a Devin worktree and the ROM tests must SKIP there, never fail. Split across `tests/rom/rom_helpers.py` (the `ROOT`, `ROM`, `STATES` constants and `load`) and `tests/rom/conftest.py` (the fixture, which imports `ROM` from `rom_helpers`):

```python
ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / "roms" / "Pokemon Red.gb"
STATES = ROOT / "tests" / "fixtures" / "rom_states"

@pytest.fixture(scope="module")
def rom_emu():
    if not ROM.exists():
        pytest.skip("needs roms/Pokemon Red.gb (gitignored; the controller runs these)")
    from pokeagent.emulator import PyBoyEmulator
    emu = PyBoyEmulator(ROM, headless=True)
    try:
        yield emu
    finally:
        emu.close()

def load(emu, name):          # returns the emulator with the state loaded and one frame ticked
    path = STATES / f"{name}.state"
    if not path.exists():
        pytest.skip(f"needs tests/fixtures/rom_states/{name}.state (controller copies it in)")
    emu.load_state(path)
    emu.tick(1)
    return emu
```

The `tick(1)` after `load_state` matches how the values below were probed; keep it. Do not import `pyboy` at module level in the test file; import `PyBoyEmulator` inside the fixture so collection never touches the emulator without a ROM. Do NOT use `POKEAGENT_ROM`; the path above is the one the repo uses.

### 3.2 The fixtures and their real values (probed 2026-11-12 with `PyBoyEmulator` headless on the laptop; pasted because you have no ROM and cannot read outside the worktree)

The controller copies each source state to `tests/fixtures/rom_states/<name>.state` (Required from User). Values are decimal unless written `0x`. "dv" is `PartyMon.dv_word` (the raw 2 DV bytes at `wPartyMon1DVs`, big-endian). Moves and PP are the 4-tuples at `wPartyMon1Moves` / `wPartyMon1PP`; `ot` is the 2-byte `wPartyMon1OTID`.

**`bedroom`** (source `baselines/bedroom.state`, no Pokemon yet): `wIsInBattle` 0, `wPartyCount` 0, `wPlayerMonNumber` 0, map 38 (`0xD35E`), `wEnemyPartyCount` 0, `wPartyGainExpFlags` 0, `wPartyFoughtCurrentEnemyFlags` 0, `wBoxCount` 0, wBattleMon species/HP/level 0, wEnemyMon species/HP/level 0, `wEnemyPartySpecies` all 0.

**`wild_stale_battle`** (source `baselines/battle.state`; a wild fight at its first frame): `wIsInBattle` 1; `wPartyCount` 1; map 12; `wPlayerMonNumber` 0; party slot 0: species 177, level 6, HP 21 / max 21, status 0, moves (33, 39, 0, 0), PP (35, 30, 0, 0), ot 55863, dv 0x84C8; `wPartyMonNicks[0:11]` = [146, 144, 148, 136, 145, 147, 139, 132, 80, 80, 80]; `wPartyMonOT[0:11]` = [129, 130, 141, 80, 0, 0, 0, 0, 0, 0, 0]. `wBattleMon` STALE: species 0, HP 15, max HP 21, level 6, `party_pos` 0. `wEnemyMon`: species 165, HP 14, max HP 14, level 3. Stale enemy party block (this is a wild fight): `wEnemyPartyCount` 1, `wEnemyPartySpecies[0:7]` = [153, 255, 0, 0, 0, 0, 0]. `wTrainerClass` 25 and `wTrainerNo` 2 are also stale leftovers; do not assert them. `wPartyGainExpFlags` 0, `wPartyFoughtCurrentEnemyFlags` 0, `wBoxCount` 0.

**`fainted_lead_overworld`** (source `runs/checkpoints/beat_brock.state`): `wIsInBattle` 0; `wPartyCount` 2; map 54; `wPlayerMonNumber` 1 (stale: no fight); slot 0: species 176, level 12, HP 0 / max 35, status 0, moves (10, 45, 52, 0), PP (35, 40, 12, 0), ot 55863, dv 0x5DA5; slot 1: species 36, level 12, HP 25 / max 32, status 0, moves (16, 28, 98, 0), PP (30, 15, 30, 0), ot 55863, dv 0xC4CD; `wPartyMonNicks[0:11]` = [130, 135, 128, 145, 140, 128, 141, 131, 132, 145, 80]; `wPartyMonOT[0:11]` = [129, 130, 141, 80, 0, 0, 0, 0, 0, 0, 0]. `wBattleMon` stale out of battle: species 36, HP 25, max 32, level 12 (equals slot 1; this is why `active_slot` must be gated on `wIsInBattle`). `wEnemyMon` species 34, HP 0, max 36, level 14. `wPartyGainExpFlags` 2, `wPartyFoughtCurrentEnemyFlags` 2, `wEnemyMonPartyPos` 1, `wEnemyPartyCount` 2, `wEnemyPartySpecies[0:7]` = [169, 34, 255, 0, 0, 0, 0]. `wBoxCount` 0.

**`trainer_single_mon`** (source `runs/discoveries/explore-20261107-161014-12400-134-level_without_xp.discovery.state`; a trainer battle, `wIsInBattle` 2): `wIsInBattle` 2; `wPartyCount` 1; map 14; `wPlayerMonNumber` 0; slot 0: species 177, level 15, HP 37 / max 43, status 0, moves (33, 39, 145, 0), PP (27, 30, 27, 0), ot 55863, dv 0x5B69. `wBattleMon`: species 177, HP 37, max 43, level 15. `wEnemyMon`: species 112, HP 0, max 29, level 10. `wTrainerClass` 2, `wTrainerNo` 4. `wPartyGainExpFlags` 1, `wPartyFoughtCurrentEnemyFlags` 1, `wEnemyMonPartyPos` 1. Enemy party: `wEnemyPartyCount` 3, `wEnemyPartySpecies[0:7]` = [123, 112, 123, 255, 0, 0, 0]; enemy struct i at `0xD8A4 + 44*i`: i=0 HP 0, level 10, max HP 30; i=1 HP 0, level 10, max HP 29; i=2 HP 30, level 10, max HP 30 (HP at struct +1/+2, level at +33, max HP at +34/+35, big-endian). Do not assert the species byte of an enemy struct (it is unreliable; use `wEnemyPartySpecies`). `wBoxCount` 0.

**`trainer_second_slot_active`** (source `runs/discoveries/explore-20261107-155157-17832-208-level_without_xp.discovery.state`; trainer battle, the second party mon is the one fighting): `wIsInBattle` 2; `wPartyCount` 2; map 3; `wPlayerMonNumber` 1; slot 0: species 133, level 9, HP 23 / max 23, moves (150, 0, 0, 0), PP (40, 0, 0, 0), ot 55863, dv 0x82DC; slot 1: species 179, level 25, HP 63 / max 69, moves (44, 39, 145, 55), PP (21, 30, 30, 25), ot 55863, dv 0x8E6C. `wBattleMon`: species 179, HP 63, max 69, level 25. `wEnemyMon`: species 150, HP 0, max 53, level 18. `wTrainerClass` 25, `wTrainerNo` 8. `wPartyGainExpFlags` 3, `wPartyFoughtCurrentEnemyFlags` 3, `wEnemyMonPartyPos` 0. `wEnemyPartyCount` 4, `wEnemyPartySpecies[0:7]` = [150, 148, 165, 153, 255, 0, 0]; enemy struct HP / level / max HP: i=0 0 / 18 / 53; i=1 34 / 15 / 34; i=2 36 / 15 / 36; i=3 45 / 17 / 45.

**`six_mons_with_box`** (source `runs/legs/states/65_4_13.state`; overworld, full party, PC box with two mons): `wIsInBattle` 0; `wPartyCount` 6; map 65; `wPlayerMonNumber` 2 (stale). Slots: 0 species 133 L11 HP 26/26 moves (150, 0, 0, 0) PP (40, 0, 0, 0) dv 0x4346; 1 species 109 L8 HP 23/23 moves (10, 0, 0, 0) PP (35, 0, 0, 0) dv 0x0447; 2 species 178 L23 HP 63/69 moves (10, 45, 52, 43) PP (35, 40, 19, 30) dv 0x199B; 3 species 169 L10 HP 29/29 moves (33, 0, 0, 0) PP (35, 0, 0, 0) dv 0xA5B3; 4 species 142 L11 HP 42/42 moves (1, 45, 0, 0) PP (35, 40, 0, 0) dv 0x60DA; 5 species 107 L9 HP 28/28 moves (141, 0, 0, 0) PP (15, 0, 0, 0) dv 0x38BF; all status 0, all ot 55863. `wPartySpecies[0:6]` = [133, 109, 178, 169, 142, 107]. `wBattleMon` stale: species 178, HP 63, max 69, level 23. `wPartyGainExpFlags` 4, `wPartyFoughtCurrentEnemyFlags` 4, `wEnemyMonPartyPos` 1. Box: `wBoxCount` 2, `wBoxSpecies[0:3]` = [36, 185, 255]; box struct i at `0xDA96 + 33*i`: i=0 species 36, HP 9, level 13 (+3), moves (16, 28, 98, 0) (+8..+11), ot 55863 (+12/+13); i=1 species 185, HP 9, level 13, moves (71, 0, 0, 0), ot 55863. `wBoxMonOT[0:11]` = [129, 130, 141, 80, 0, 0, 0, 0, 0, 0, 0]; `wBoxMonNicks[0:11]` = [143, 136, 131, 134, 132, 152, 80, 80, 80, 80, 80].

### 3.3 Addresses (pasted from `pokered.sym`; `.devin-scratch/pokered.sym` is gitignored and not in your worktree)

```
00:cc2f wPlayerMonNumber
00:ccf5 wPartyFoughtCurrentEnemyFlags
00:cfe5 wEnemyMon                  (29-byte battle struct; species +0, HP +1/+2 big-endian, level +14, max HP +15/+16)
00:cfe8 wEnemyMonPartyPos
00:d014 wBattleMon                 (29-byte battle struct; species +0, HP +1/+2, level +14, max HP +15/+16)
00:d031 wTrainerClass
00:d057 wIsInBattle
00:d058 wPartyGainExpFlags
00:d05d wTrainerNo
00:d163 wPartyCount
00:d164 wPartySpecies
00:d16b wPartyMon1                 (44-byte party struct; read through pokeagent.ramstructs.read_party)
00:d273 wPartyMonOT                (11 bytes per slot)
00:d2b5 wPartyMonNicks             (11 bytes per slot)
00:d35e (current map; the repo's CUR_MAP)
00:d89c wEnemyPartyCount
00:d89d wEnemyPartySpecies
00:d8a4 wEnemyMons                 (44-byte structs; HP +1/+2, level +33, max HP +34/+35)
00:da80 wBoxCount
00:da81 wBoxSpecies
00:da96 wBoxMons                   (33-byte structs; species +0, HP +1/+2, level +3, moves +8..+11, OTID +12/+13)
00:dd2a wBoxMonOT                  (11 bytes per slot)
00:de06 wBoxMonNicks               (11 bytes per slot)
```

Use `pokeagent.ramstructs` for what it already decodes (`read_party`, `read_battle_mon`, `read_enemy_mon`; `PartyMon` fields: `species, hp, status, moves, ot_id, dv_word, pp, level, max_hp`; `BattleMon` fields: `species, hp, party_pos, status, moves, level, max_hp` and more) and raw `emu.read` / `emu.read_range` at the literal addresses above for everything else. Test files may use literals (they are exempt from the one-constant rule); put the addresses in one table at the top of the test module, named after their symbols. Reads are `emu.read(addr)` and a big-endian helper `(emu.read(a) << 8) | emu.read(a + 1)`.

### 3.4 What the test asserts and the coverage table

`tests/rom/test_party_states.py` has one test function per fixture (`test_bedroom`, `test_wild_stale_battle`, `test_fainted_lead_overworld`, `test_trainer_single_mon`, `test_trainer_second_slot_active`, `test_six_mons_with_box`), each taking the module `rom_emu` fixture and loading its state through `load(...)`, each asserting EVERY value pasted for that fixture, field by field, with a message naming the symbol (`assert party[1].hp == 25, "wPartyMon2HP"`). Assert the stale values explicitly as well: in `wild_stale_battle`, `read_battle_mon(emu).species == 0` while `.hp == 15` and `.level == 6`; in `fainted_lead_overworld`, the stale `wBattleMon` species 36 with `wIsInBattle` 0.

In `tests/rom/party_states_covered.py` define the coverage table the controller uses to flip `ram_map.json`:

```python
COVERED = {   # symbol -> the test that asserts it, on at least one state
    "wPartyCount": "test_six_mons_with_box", ...
}
```

It must list exactly the symbols asserted by a test above: wPartyCount, wPartySpecies, wPartyMon1 (struct via read_party), wPartyMonOT, wPartyMonNicks, wIsInBattle, wBattleMon, wEnemyMon, wPlayerMonNumber, wPartyGainExpFlags, wPartyFoughtCurrentEnemyFlags, wEnemyMonPartyPos, wEnemyPartyCount, wEnemyPartySpecies, wEnemyMons (HP / level / max HP only), wBoxCount, wBoxSpecies, wBoxMons, wBoxMonOT, wBoxMonNicks. Not covered and left `verified: false`: `wWhichPokemon` 0xCF92, `wPartyMenuTypeOrMessageID` 0xD07D (no stable state value; do not list them), `wTrainerClass` / `wTrainerNo` (only asserted in the two trainer states: list them, mapped to those tests).

`tests/rom/test_party_states_table.py` (runs WITHOUT a ROM, in your worktree): load `pokeagent.ram_lookup.load_map()` (it returns entries with `.name` and `.addr`; confirm the attribute names by reading `src/pokeagent/ram_lookup.py`) and assert (importing `from party_states_covered import COVERED`) that every `COVERED` key exists in the map by name and that its address equals the one pasted in 3.3 (a table of name -> expected address in the test, from the pasted block, never recomputed from the map); assert every symbol in the "Why" list above that the tests cover is in `COVERED`; assert `wWhichPokemon` and `wPartyMenuTypeOrMessageID` are not.

The `ram_map.json` flags stay false in this PR. Rule (Robert's, via the controller): an entry is `"verified": true` only when a passing ROM test asserts it. You cannot run the ROM tests, so you do not flip anything. After merge Claude runs them, and for each `COVERED` symbol that passes sets `"verified": true` and `"evidence": "asserted by tests/rom/test_party_states.py <date>"` in `ram_map.json` (and `ram_names.json` if it carries the flag).

## 4. What NOT to do

- Do not run an emulator or a ROM; none exists in this worktree. Do not search, glob or hunt for `roms/`, `baselines/`, `runs/` or any `.state`; absence is a skip, that is the whole behaviour.
- Do not copy, create, commit or print a ROM or any `.state` file; do not say where any game copy came from in code, comments or the report. (States are copied in by the controller, not you.)
- Do not edit `src/pokeagent/data/ram_map.json`, `ram_names.json`, any `src/` file, `tests/test_real_rom.py`, `tests/test_golden_red.py`, `agentflow.toml`, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Do not change a pasted value to make a test pass; you cannot check them, so a mismatch is the controller's to settle on the ROM run.
- Do not add a PartyView/BattleView assertion (that code is `Party_View_Directive.md`'s; the controller adds the cross-check after both merge).
- Do not use `POKEAGENT_ROM`. No file over 600 lines.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/rom/test_party_states.py
```
Expected in this worktree (no ROM): every test skipped (6 skipped), 0 failed, exit 0, the skip reason names `roms/Pokemon Red.gb`.

```
uv run pytest -q -p no:cacheprovider tests/rom/test_party_states_table.py
```
Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider
```
Baseline on `origin/main` (measured 2026-11-12): `2499 passed, 41 skipped, 1 warning in 186.93s (0:03:06)`. Expected: 2499 + your table tests passed, 41 + 6 skipped, zero failed. About three minutes; run once at the end.

```
git status --short
```
Expected: only the five new files under `tests/rom/` (`conftest.py`, `rom_helpers.py`, `party_states_covered.py`, `test_party_states.py`, `test_party_states_table.py`).

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] `tests/rom/test_party_states.py` asserts every pasted value for the six fixtures, field by field, and skips (does not fail) without the ROM or a state. <!-- test: tests/rom/test_party_states.py -->
- [ ] `COVERED` names exactly the asserted symbols, and each name and address matches the pasted block. <!-- test: tests/rom/test_party_states_table.py -->
- [ ] In this worktree the ROM tests skip with a reason naming `roms/Pokemon Red.gb`; the table tests pass.
- [ ] Full suite: zero failed; baseline 2499 passed / 41 skipped plus your additions.
- [ ] No ROM, state, `.gitattributes`, `ram_map.json` or `src/` change (states and `.gitattributes` were committed before dispatch).

## 8. Report

Findings first: any pasted value you could not turn into an assertion and why, and the exact skip line pytest printed. Then the tails of the pytest commands. State plainly that no ROM was available, so no assertion has been run against real bytes and no `verified` flag was changed; the controller runs the ROM tests and owns the flag flips.

## Required from User

Controller (Claude) steps, not Devin's. They must happen before the ROM tests can do anything:

1. DONE before dispatch (2026-11-12, with this directive's PR): copied these untracked states into the repo as `tests/fixtures/rom_states/<name>.state` and committed them (Robert's rule: save states are allowed, ROMs never; each is about 178 KB (178,108 bytes), six files in all). The `.gitattributes` from section 2 marks them binary. A state is a snapshot of RAM, VRAM and CPU state, not a ROM image; measured on `baselines/battle.state`: the ROM header title bytes (`POKEMON RED`) are not present, and only 5 of 443 sampled high-entropy 64-byte ROM chunks appear (tile graphics the game copied into VRAM). Do not commit `roms/` (gitignored), a ROM hash, or any absolute path to a ROM; the only ROM reference in the repo is the relative gitignored path `roms/Pokemon Red.gb`, which `tests/test_golden_red.py` already uses. Before committing run `git ls-files roms` (expect no output) and `git diff --cached --stat` (expect only the six `.state` files, `.gitattributes` and the tests):
   - `baselines/bedroom.state` -> `bedroom.state`
   - `baselines/battle.state` -> `wild_stale_battle.state`
   - `runs/checkpoints/beat_brock.state` -> `fainted_lead_overworld.state`
   - `runs/discoveries/explore-20261107-161014-12400-134-level_without_xp.discovery.state` -> `trainer_single_mon.state`
   - `runs/discoveries/explore-20261107-155157-17832-208-level_without_xp.discovery.state` -> `trainer_second_slot_active.state`
   - `runs/legs/states/65_4_13.state` -> `six_mons_with_box.state`
2. Run `uv run pytest -q -p no:cacheprovider tests/rom/test_party_states.py` on the laptop (ROM at `roms/Pokemon Red.gb`). Expect 6 passed. A failing assertion means a pasted value is wrong or the state drifted: fix the test, never the state.
3. Flip `verified` for the `COVERED` symbols that passed, with evidence text, in `ram_map.json`; leave the rest false.
4. The audit found no trainer-battle or box-holding state tracked in git; the six above cover kind 2 and a non-empty box, but they are untracked captures. If Robert wants them reproducible, Claude captures purpose-made trainer-battle (Brock) and PC-box states with the repo's state tools and swaps them in; that is a separate, later step.
5. After `Party_View_Directive.md` merges, add `PartyView` / `BattleView` cross-checks against the same six states.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/ramstructs.py)
- Read(src/pokeagent/ram_lookup.py)
- Read(src/pokeagent/emulator.py)
- Read(tests/test_real_rom.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-party-ram-state-tests-directive |
| Base branch | - |
| Base commit | c18ac0803665ce5c59dcb05c99c5d26304255785 |

**Status log**
- 2026-11-12 08:14 · robert-claude-laptop · none → Queued — Robert 2026-11-12: expand party RAM/ROM detection; fixtures committed with PR #207 (fb27482)
- 2026-11-12 08:14 · robert-claude-laptop · Queued → Approved
- 2026-11-12 08:14 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-party-ram-state-tests-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M77YAMQ1D4FSMPN18B57D2C1
- 2026-11-12 08:20 · dispatcher · launched pid=2704; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-party-ram-state-tests-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (7 declared need(s); 4 external))
<!-- queue:end -->
