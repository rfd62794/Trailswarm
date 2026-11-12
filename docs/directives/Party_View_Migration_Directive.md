# Trailswarm: move the remaining slot-0 and stale-battle readers onto PartyView and delete the duplicate address constants

**Size:** M. **Assignee:** devin.

**Depends on:** `Party_View_Directive.md` merged (it creates `src/pokeagent/ram_symbols.py` <!-- new: src/pokeagent/ram_symbols.py -->, `src/pokeagent/party_view.py` <!-- new: src/pokeagent/party_view.py -->, and rewires `magikarp.fighter`, `perceive.party_hp`, `perceive.lead_level`, `perceive.true_lead_level`). If either new module is missing from your worktree, stop and say so in the PR description; do not recreate them.

## Why this is a separate directive (the split decision)

The first directive adds two modules plus tests and rewires four hub functions: one reviewable PR with a clear contract. The migration touches about 30 files across the explorer, intervene, adapters and goals code, each a small edit but each with its own existing tests, and a single run that did both would mix "is the new view right" with "did 30 call sites survive". Splitting keeps the first review about the view and this one about mechanical, test-guarded replacement. A migration that goes wrong is one revert.

## 1. Why this exists

Audit 2026-11-12, re-verified on `origin/main` (3f73696). After the view exists, these direct readers still assume slot 0 is the lead or trust a stale `wBattleMon`, and the same address literals are defined over and over.

**Slot-0 / stale readers still to move:**

- `src/pokeagent/explorer/behaviours/bring_out.py`: `able_slot` (lines ~15-21) computes party HP by hand with `PARTY_HP + MON_STRIDE * i` and species from `PARTY_SPECIES + i`; `forced_faint_prompt` (line ~24, `BATTLER_HP = 0xD015`) reads the battler's HP with no species gate. When wBattleMon is not loaded (species 0) it reads leftover HP, so the prompt can be misjudged forced/voluntary.
- `src/pokeagent/explorer/behaviours/already_out.py:41`: `ctx.emu.read(0xD015) == 0 and ctx.emu.read(0xD016) == 0` (battler HP, ungated).
- `src/pokeagent/explorer/perceive.py` `battle_view` (line ~118): prints `you L{0xD022} HP {0xD015}/{0xD023}` ungated, and `0xD057` as the kind.
- `src/pokeagent/explorer/press.py:58,65`: `"you": [read(0xD014), read(0xD022)]` and `"hp_you": u16(0xD015)`; `press.py:138`: `party={read(0xD163)}`.
- `src/pokeagent/adapters/event_feed.py:72-76`: `hp = (_u16(emu, 0xD015), _u16(emu, 0xD023), ...)`, `own_species=read(0xD014)`, `own_level=read(0xD022)`.
- `src/pokeagent/observations.py:62`: `read(0xD022)`, `4*u16(0xD015)//maximum`.
- `src/pokeagent/explorer/behaviours/cave_topup.py` `fighter_slot` (lines 28-35): returns slot 0 unless a Magikarp is present.
- `src/pokeagent/explorer/item_policies/view.py` `fighter_slot_of` (lines 30-38): "slot 0 without a Magikarp, else the strongest non-Magikarp". Its docstring says it is the same rule as `cave_topup.fighter_slot` and `magikarp.fighter`; it works on plain `Mon` data.
- `src/pokeagent/explorer/item_policies/policy.py:61`: `rare_candy.atlas_minutes(atlas, party[0].name, goal, party[0].level, ...)` (slot 0 assumed lead).
- `src/pokeagent/explorer/item_policies/xitems_battle.py:33`: `best_move(party[0], boss[0], ...)` (slot 0 assumed lead).
- `src/pokeagent/explorer/ram_event_kinds.py:15-16`: `IN_BATTLE, CUR_MAP, PARTY_COUNT, PARTY_SPECIES, MONEY = 0xD057, 0xD35E, 0xD163, 0xD164, 0xD347` and `ENEMY_SPECIES, LEAD_HP, LEAD_MAXHP = 0xCFE5, 0xD16C, 0xD18D`.
- `src/pokeagent/explorer/interaction_types.py:12-13`: `A_BATTLE, A_PARTY_N, A_PARTY, ... = 0xD057, 0xD163, 0xD16B, ...` and `PARTY_STRIDE, A_HP, A_MAXHP, FLAG_BYTES = 44, 0xD16C, 0xD18D, 320`.
- `src/pokeagent/explorer/behaviours/menu.py:43`: `ctx.emu.read(0xD173 + i)` (slot 0's moves, in the "learn a move" prompt: whichever mon is learning, not necessarily the lead).
- `src/pokeagent/explorer/behaviours/item_use.py:84`: `slot = emu.read(PLAYER_MON) if party_target is None else party_target` (raw wPlayerMonNumber; the comment says "outside a fight 0xCC2F is stale: the caller says who").
- `src/pokeagent/goals.py:51-56`: all-party-full-HP check reading `0xD16C + 0x2C * i`; `src/pokeagent/legs/states.py:29`, `src/pokeagent/procedures/predicates.py:82`: lead HP / max HP by literal; `src/pokeagent/explorer/press_track.py:49,73`: `read(0xD18C)` (lead level) and `src/pokeagent/campaign.py:96,121` (`0xD163`, `0xD173`).
- `src/pokeagent/explorer/behaviours/battle_moves.py:85` and `src/pokeagent/explorer/battle.py:144`: moves (`0xD01C + slot`) and PP (`0xD02D + slot`) of the active mon read ungated (stale at battle start).

**Duplicate address constants (measured with `git grep -n -i -E "0xD163|0xCC26|0xD057|0xCC2F" -- src ':!src/pokeagent/data'` on origin/main: 52 lines in 30 files):** `adapters/event_feed.py`, `campaign.py` (2), `explorer/anomalies.py`, `explorer/behaviours/battle.py` (4), `box_settle.py`, `bring_out.py`, `guards.py` (5), `item_use.py` (3), `party_order.py`, `procedures.py` (2), `switch_out.py`, `explorer/interaction_gate.py`, `interaction_types.py`, `party_menu.py` (2), `perceive.py` (2), `press.py` (3), `press_track.py`, `ram_event_kinds.py`, `text_press.py`, `goals.py` (4), `intervene/extra.py`, `intervene/rig.py`, `legs/states.py`, `magikarp.py`, `observations.py` (2), `options.py`, `ram.py` (2), `ramstructs.py` (3), `ramworld.py`, `statemeta.py`. (`tools/*.py` also carry these literals; they are out of scope, see section 4.)

### The contract you are migrating onto (written by `Party_View_Directive.md`; read `src/pokeagent/party_view.py` and `ram_symbols.py` in your worktree to confirm names before editing)

```python
# party_view.py
PartySlot(index, species, level, hp, max_hp, status, moves, pp, ot_id, dv_word, nickname)  # .fainted -> hp <= 0
PartyView(slots, count, in_battle, active_slot)   # active_slot: VERIFIED or None; .lead, .fighter() -> PartySlot | None
BattleView(kind, battle_mon, enemy_mon, enemy_party_pos, participants, enemy_party)
    # battle_mon is None while wBattleMonSpecies == 0; enemy_party only when kind == 2
read_party_view(emu) -> PartyView ; read_battle_view(emu) -> BattleView   # both memoized per frame
# ram_symbols.py: PARTY_COUNT, PARTY_SPECIES, PARTY_MON1, PARTY_MON_SIZE, MAX_PARTY, BATTLE_MON, ENEMY_MON,
#   IS_IN_BATTLE, PLAYER_MON_NUMBER, MENU_ITEM, PARTY_GAIN_EXP_FLAGS, PARTY_FOUGHT_ENEMY_FLAGS, ... (one per symbol)
```

`lead` = first non-fainted slot out of battle (slot 0 if every slot has fainted); `fighter()` = the lead, except that with a MAGIKARP in the party it is the battle's active slot in a fight or the strongest non-Magikarp (max by `(hp > 0, level, hp)`).

### Ground-truth symbols (pasted; `.devin-scratch/pokered.sym` is gitignored and not in your worktree)

```
00:cc26 wCurrentMenuItem
00:cc2f wPlayerMonNumber
00:cfe5 wEnemyMon
00:d014 wBattleMon
00:d015 wBattleMonHP
00:d022 wBattleMonLevel
00:d023 wBattleMonMaxHP
00:d02d wBattleMonPP
00:d057 wIsInBattle
00:d163 wPartyCount
00:d164 wPartySpecies
00:d16b wPartyMon1Species
00:d16c wPartyMon1HP
00:d173 wPartyMon1Moves
00:d18c wPartyMon1Level
00:d18d wPartyMon1MaxHP
```

Party struct stride 44 (0x2C). wBattleMon is stale at battle start: species 0 while HP/level/PP hold leftovers. wIsInBattle: 0 overworld, 1 wild, 2 trainer.

## 2. Scope (one PR, in order)

1. Constants: replace every definition and literal of 0xD163, 0xCC26, 0xD057, 0xCC2F in `src/` (the 30 files above) with an import from `pokeagent.ram_symbols` (or `ramstructs`, where that file already re-exports the name). One constant per symbol; no file defines its own.
2. Gate the ungated battle-mon readers: `bring_out.forced_faint_prompt`, `already_out`, `perceive.battle_view`, `press.py`, `adapters/event_feed.py`, `observations.py`, `battle_moves.py` and `explorer/battle.py:144` move/PP reads.
3. Move the slot-0 readers onto the view: `bring_out.able_slot`, `cave_topup.fighter_slot`, `item_policies/view.fighter_slot_of`, `item_policies/policy.py:61`, `xitems_battle.py:33`, `ram_event_kinds.py`, `interaction_types.py`, `goals.py` (all-full-HP), `legs/states.py`, `procedures/predicates.py`, `press_track.py`, `menu.py:43`, `item_use.py:84`, `campaign.py`.
4. Tests: extend the existing test files that cover each reader with the stale/fainted cases below, plus `tests/test_party_view_migration.py` <!-- new: tests/test_party_view_migration.py --> for the grep-style guards.

## 3. The work

**3.1 Constants.** In each file, delete the local definition (e.g. `PARTY_COUNT, PARTY_SPECIES, PARTY_HP, MON_STRIDE, MENU_ITEM = 0xD163, 0xD164, 0xD16C, 0x2C, 0xCC26` in `bring_out.py`) and `from pokeagent.ram_symbols import ...`. Keep any local name other modules import (for example `from pokeagent.explorer.interaction_gate import BATTLE_FLAG`, `explorer/__init__.py` re-exports `BATTLE_FLAG`, `legacy.py` imports it): keep the name, bind it to the imported constant (`BATTLE_FLAG = IS_IN_BATTLE`). Replace bare literals in code and in comments/docstrings with the symbol name (a docstring may say "wCurrentMenuItem" but not the hex). `ram.py`'s dict (`"party_count": 0xD163`, `"in_battle": 0xD057`) uses the constants.

**3.2 Gating.** Every HP, level, species or PP read of wBattleMon outside `ramstructs`/`party_view` goes through `read_battle_view(emu).battle_mon`; when it is `None` the reader treats the battle as "not loaded": `forced_faint_prompt` returns False, `already_out` returns None (no press), `battle_view` prints `you  (not loaded)` instead of leftover numbers, `press.py` logs `"you": [0, 0]` and `hp_you: 0`, `event_feed` yields no own mon and an empty hp tuple as it does when not in battle, `observations` returns 0 buckets, `battle_moves` and `explorer/battle.py` treat moves/PP as unknown (falls back exactly as its existing "stale all-zero PP read" branch does). Behaviour when the battle mon IS loaded must not change.

**3.3 Lead and fighter.**
- `bring_out.able_slot(emu)`: from `read_party_view`: alive slots = not fainted; the first alive non-MAGIKARP (`SPECIES_MAGIKARP`), else the first alive, else None. Same results as today for every input today's tests cover.
- `cave_topup.fighter_slot(emu)` returns `read_party_view(emu).fighter().index` (0 for an empty party, as today's fallback). Update the docstring: it now matches `fighter()`.
- `item_policies/view.fighter_slot_of(party: list[Mon])` works on plain data, so it cannot call the view; make it the lead rule on `Mon`s: no MAGIKARP present -> the first non-fainted `Mon` (slot of it), else slot 0 if all fainted; with a Magikarp: unchanged (strongest non-Magikarp, `None` if only Magikarps). Keep its signature. The three duplicated implementations (`cave_topup.fighter_slot`, `view.fighter_slot_of`, `magikarp.fighter`) must now agree; a test pins that.
- `policy.py:61` and `xitems_battle.py:33`: replace `party[0]` with the fighter's entry: index `fighter_slot_of(...)` into the same list (for `xitems_battle`, `party` there is `[c for c in our_party(...) if c.name != "MAGIKARP"]`, so use its first non-fainted entry, else `party[0]`). Do not change which move or item the code picks when the lead is healthy.
- `ram_event_kinds.py`: `LEAD_HP` / `LEAD_MAXHP` stay as event-diff addresses (they watch a fixed RAM byte for change, which is what an event stream wants); define them from `PARTY_MON1 + 1` and `PARTY_MON1 + 0x22` in `ram_symbols` terms rather than as new literals, and add a comment saying they intentionally watch slot 0's bytes, not the lead. Same for `interaction_types.A_HP/A_MAXHP`. If you judge that changing them would change the event stream, leave the values and only remove the literals.
- `goals.py`, `legs/states.py`, `procedures/predicates.py`: "party at full HP" uses `read_party_view(...).slots`; the lead HP fraction in `legs/states.py` and `predicates.py` uses `party_hp`'s rule (`.fighter()` HP, or the lead rule), not 0xD16C.
- `press_track.py:49,73`: the level read for XP tracking uses `perceive.true_lead_level(emu)`.
- `menu.py:43`: the "learn a move" prompt shows the CURRENT moves of the mon that is learning; the dialog does not say which, so use `read_party_view(emu).fighter()`'s `moves` (names via `ROM_KB`, as the line does today), not slot 0's bytes.
- `item_use.py:84`: `slot = party_target if party_target is not None else (view.active_slot if view.active_slot is not None else view.fighter().index)`; delete the raw `PLAYER_MON` read and its constant.
- `campaign.py:96,121`: constants from `ram_symbols`; `0xD173` moves via the party view's slots (`PartySlot.moves`) if the campaign checks "a party mon knows move X" for any slot; otherwise leave the semantics and only replace the literals with `PARTY_MON1 + ...` constants.

**3.4 Tests.** For each reader moved in 3.2 and 3.3, add one test to its existing test file (the files in section 5 cover most: `tests/test_cave_topup.py`, `tests/test_item_policies.py`, `tests/test_magikarp.py`, `tests/test_anomalies.py`, `tests/test_intervene_macros.py`, `tests/test_switch_matchup.py`, `tests/test_bandit.py`; make a small new file only when none exists) in the same FakeEmulator style:
- fainted lead + live second: the reader acts on slot 1 (cave top-up targets slot 1's potion, `able_slot` is 1, goals "full HP" is False when slot 1 is hurt).
- stale wBattleMon (species 0, nonzero HP): `forced_faint_prompt` is False, `battle_view` does not print leftover numbers, `already_out` presses nothing.
- unchanged behaviour for a healthy lead (one assertion per reader).
- `tests/test_party_view_migration.py`: `fighter_slot_of`, `cave_topup.fighter_slot` and `magikarp.fighter` return the same slot for six hand-built parties (healthy, fainted lead, Magikarp lead, Magikarp second, all fainted, single mon); and the guard: read every `.py` under `src/pokeagent` except `ram_symbols.py` and the `data/` directory with `pathlib` and assert none contains `0xD163`, `0xCC26`, `0xD057` or `0xCC2F` (case-insensitive).

## 4. What NOT to do

- Do not edit `ram_symbols.py` or `party_view.py` beyond a missing constant you need; if a name in the contract is wrong or absent, stop and say so in the PR description.
- Do not touch `ramstructs.active_slot` (intervene code depends on it), `src/pokeagent/data/*.json`, `agentflow.toml`, protected repos, `retalk_veto.py`, `loop_veto.py`.
- Do not migrate `tools/*.py` (`explore_demo.py`, `make_state.py`, `make_battle_state.py`, `ram_checks.py`, `rl_env.py`, `rl_verify_battle.py`, `score_check.py`): they have no unit tests here, and some are used for ROM work only.
- Do not change a test's expected value to make it pass. If an existing test fails and you believe the test is wrong, stop and say which in the PR description.
- Do not change behaviour for a healthy lead, a loaded battle mon, or a non-Magikarp party: this directive only changes the fainted-lead and stale-battle cases.
- Do not add or remove behaviours, no new features, no new dependencies. Do not run a ROM or emulator; none exist in this worktree and do not search for one.
- No file over 600 lines; each `explorer/*.py` you touch stays under 300 if it is under 300 now.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
git grep -n -i -E "0xD163|0xCC26|0xD057|0xCC2F" -- src ':!src/pokeagent/data' ':!src/pokeagent/ram_symbols.py'
```
Baseline before this directive: 52 lines in 30 files. Expected after: no output.

```
git grep -n -E "emu\.read\((0x)?[Dd]01[45]\)|0xD014|0xD015|0xD022|0xD023|0xD02D" -- src ':!src/pokeagent/data' ':!src/pokeagent/ram_symbols.py' ':!src/pokeagent/ramstructs.py' ':!src/pokeagent/party_view.py'
```
Expected: no output (wBattleMon fields are read only inside the view layer).

```
uv run pytest -q -p no:cacheprovider tests/test_ramstructs.py tests/test_magikarp.py tests/test_bandit.py tests/test_cave_topup.py tests/test_item_policies.py tests/test_ram_map.py tests/test_anomalies.py tests/test_intervene_macros.py tests/test_switch_matchup.py tests/test_intervene_lease.py tests/test_party_view.py tests/test_ram_symbols.py tests/test_party_view_migration.py
```
Baseline on `origin/main` for the first ten files (measured 2026-11-12): `280 passed, 1 warning in 5.78s`. Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider
```
Baseline on `origin/main` (measured 2026-11-12): `2499 passed, 41 skipped, 1 warning in 186.93s (0:03:06)`. Expected: the baseline plus the tests of the first directive and this one passed, zero failed, the same 41 skipped. About three minutes; run it once at the end.

```
git status --short
```
Expected: only `src/` files named in section 2, the test files, and `tests/test_party_view_migration.py`.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] The first grep in section 5 prints nothing; the second prints nothing. <!-- test: tests/test_party_view_migration.py -->
- [ ] With a fainted lead and a live second mon, `able_slot`, `cave_topup.fighter_slot`, `fighter_slot_of`, the goals full-HP check and the policy / x-item lead lookups act on slot 1. <!-- test: tests/test_party_view_migration.py -->
- [ ] With a stale wBattleMon (species 0), `forced_faint_prompt`, `already_out`, `battle_view`, `press.py` and `event_feed` do not use its HP or level. <!-- test: tests/test_cave_topup.py -->
- [ ] `cave_topup.fighter_slot`, `fighter_slot_of` and `magikarp.fighter` agree on six pinned parties. <!-- test: tests/test_party_view_migration.py -->
- [ ] Full suite: zero failed, same 41 skipped as the baseline.
- [ ] No `tools/` file, data file or `ramstructs.active_slot` changed.

## 8. Report

Findings first: every reader you moved, any you left and why (with the file and line), and any place the gated read changed a healthy-path result (must be none). Then the output of the two greps (both empty) and the tails of the two pytest commands. State plainly that no ROM was available and the real-state confirmation is the controller's (`Party_RAM_State_Tests_Directive.md` states). List `tools/*.py` as the remaining duplicates for a later pass.

## Required from User

Nothing for the build. After merge, Claude runs the ROM state tests (`tests/rom/test_party_states.py`) and a hands-off check (`tools/hands_off_check.py`) on the laptop to confirm behaviour for a healthy lead is unchanged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/party_view.py)
- Read(src/pokeagent/ram_symbols.py)
- Read(tests/test_cave_topup.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git status)
