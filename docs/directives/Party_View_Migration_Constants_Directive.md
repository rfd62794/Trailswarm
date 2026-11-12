# Trailswarm: one constant per RAM symbol and species-gated battle-mon reads, so duplicate addresses and stale wBattleMon values stop leaking

**Size:** M. **Assignee:** devin.

**Depends on:** `Party_View_Directive.md` merged (it creates `src/pokeagent/ram_symbols.py` <!-- new: src/pokeagent/ram_symbols.py --> and `src/pokeagent/party_view.py` <!-- new: src/pokeagent/party_view.py -->). If either is missing from your worktree, stop and say so in the PR description; do not recreate them. The follow-up `Party_View_Migration_Lead_Directive.md` (lead/fighter readers) depends on this one.

## Why this is a separate directive (the split decision)

The migration was one directive and was too big for a run: about 30 files of constant edits plus about 15 lead/fighter rewrites with their own tests. This one is the mechanical half: replace duplicate address constants and gate stale battle-mon reads. It changes no lead or fighter logic. `Party_View_Migration_Lead_Directive.md` is the judgement half.

## 1. Why this exists

Audit 2026-11-12, re-verified on `origin/main` (3f73696; #206 has merged since).

**Duplicate address constants.** 0xD163 (`PARTY_COUNT`), 0xCC26 (`MENU_ITEM`), 0xD057 (`wIsInBattle`, named `IN_BATTLE` / `BATTLE_FLAG` / `A_BATTLE`) and 0xCC2F (`PLAYER_MON`) are defined or written as literals across about 30 files in `src/` (`adapters/event_feed.py`, `campaign.py`, `explorer/anomalies.py`, `behaviours/battle.py`, `box_settle.py`, `bring_out.py`, `guards.py`, `item_use.py`, `party_order.py`, `procedures.py`, `switch_out.py`, `interaction_gate.py`, `interaction_types.py`, `party_menu.py`, `perceive.py`, `press.py`, `press_track.py`, `ram_event_kinds.py`, `text_press.py`, `goals.py`, `intervene/extra.py`, `intervene/rig.py`, `legs/states.py`, `magikarp.py`, `observations.py`, `options.py`, `ram.py`, `ramstructs.py`, `ramworld.py`, `statemeta.py`). The count on your base commit is deliberately NOT pasted, because the first directive changes it. Re-measure it after the first directive has landed, with this exact command, and put the number in your PR description:

```
git grep -n -i -E "0xD163|0xCC26|0xD057|0xCC2F" -- src ':!src/pokeagent/data' ':!src/pokeagent/ram_symbols.py'
```

(Before the first directive it printed 52 lines in 30 files; treat that as history, not the baseline.) `tools/*.py` carry the same literals and are out of scope (a later follow-up, once they have tests).

**Ungated battle-mon reads.** wBattleMon is half-filled at battle start (measured: `wBattleMonSpecies` 0 with HP 15, level 6, max 21 left over). These read its HP, level, species, moves or PP with no species check: `behaviours/bring_out.py:24` (`BATTLER_HP = 0xD015`, used by `forced_faint_prompt`), `behaviours/already_out.py:41` (0xD015/0xD016), `explorer/perceive.py:118` (`battle_view`: 0xD022, 0xD015, 0xD023), `explorer/press.py:58,65` (0xD014, 0xD022, 0xD015), `adapters/event_feed.py:72-76` (0xD015, 0xD023, 0xD014, 0xD022), `observations.py:60-64` (0xD023, 0xD022, 0xD015, 0xD01C, 0xD02D), `behaviours/battle_moves.py:85` (0xD02D PP), `explorer/battle.py:144` (0xD01C moves, 0xD02D PP) and `intervene/screen.py:13` (`BATTLE_MOVES = 0xD01C`, a duplicate of the symbol). Measured with (it covers 0xD016, 0xD01C and 0xD024 as well as the main fields):

```
git grep -n -E "0xD014|0xD015|0xD016|0xD01C|0xD022|0xD023|0xD024|0xD02D|emu\.read\((0x)?[Dd]01[45]\)" -- src ':!src/pokeagent/data' ':!src/pokeagent/ram_symbols.py' ':!src/pokeagent/ramstructs.py' ':!src/pokeagent/party_view.py'
```

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

1. Constants: replace every definition and literal of 0xD163, 0xCC26, 0xD057, 0xCC2F in `src/` with an import from `pokeagent.ram_symbols` (or `ramstructs`, where that file already re-exports the name). One constant per symbol; no file defines its own.
2. Add to `ram_symbols.py` any constant the sweep needs that is missing (`BATTLE_MON_HP`, `BATTLE_MON_LEVEL`, `BATTLE_MON_MAX_HP`, `BATTLE_MON_MOVES`, `BATTLE_MON_PP` if absent), one per symbol in the pasted list, and add the matching row to `tests/test_ram_symbols.py`.
3. Gate the battle-mon readers listed above through `read_battle_view(emu).battle_mon`.
4. One-line "slot 0 is intentional" comments at `ram_event_kinds.LEAD_HP` / `LEAD_MAXHP` and `interaction_types.A_HP` / `A_MAXHP` (they watch slot 0's fixed bytes for change; they are not "the lead"). Their values may stay; define them from `PARTY_MON1`-based constants instead of literals.
5. Tests: the gating cases and the grep guard in 3.3.

## 3. The work

**3.1 Constants.** In each file delete the local definition (for example `PARTY_COUNT, PARTY_SPECIES, PARTY_HP, MON_STRIDE, MENU_ITEM = 0xD163, 0xD164, 0xD16C, 0x2C, 0xCC26` in `bring_out.py`) and `from pokeagent.ram_symbols import ...`. Keep any local name another module or a test imports, bound to the imported constant. Known cases:
- `explorer/interaction_gate.py` `BATTLE_FLAG`, `explorer/__init__.py` (re-exports `BATTLE_FLAG`), `explorer/legacy.py` (imports it), `magikarp.IN_BATTLE`, `perceive.BATTLE_FLAG`: keep the names, `BATTLE_FLAG = IS_IN_BATTLE`.
- `behaviours/item_use.py`: KEEP `PLAYER_MON` and `MENU_ITEM` as module-level names (`PLAYER_MON = PLAYER_MON_NUMBER`, `MENU_ITEM` imported from `ram_symbols`) because `tests/test_item_use.py:47` uses `iu.PLAYER_MON` and `iu.MENU_ITEM`; `LIST_SCROLL` stays. Do not change the `slot = emu.read(PLAYER_MON)` line in this directive (it moves in the Lead directive).
- `intervene/screen.py` re-exports `PLAYER_MON` (a `noqa: F401` import): keep that re-export working.
- `ram.py`'s dict (`"party_count": 0xD163`, `"in_battle": 0xD057`) uses the constants.
Replace bare hex literals in comments and docstrings too (say "wCurrentMenuItem", not the hex).

**3.2 Gating.** Every HP, level, species, moves or PP read of wBattleMon outside `ramstructs` / `party_view` goes through `read_battle_view(emu).battle_mon`; when it is `None` the reader treats the battle as not loaded: `forced_faint_prompt` returns False; `already_out` presses nothing; `battle_view` prints `you  (not loaded)` instead of leftover numbers; `press.py` logs `"you": [0, 0]` and `hp_you: 0`; `event_feed` yields no own mon and an empty hp tuple, as it does when not in battle; `observations` returns zero buckets; `battle_moves` and `explorer/battle.py:144` treat moves/PP as unknown (`battle_moves` falls back exactly as its existing "stale all-zero PP read" branch does). `intervene/screen.py:13` `BATTLE_MOVES` becomes the `ram_symbols` constant. When the battle mon IS loaded nothing changes.

**3.3 Tests.** One test per gated reader, in FakeEmulator style, in the existing test file that builds the needed context (`tests/test_intervene_macros.py` and `tests/test_anomalies.py` already build battle contexts; if none fits, put it in `tests/test_battle_mon_gating.py` <!-- new: tests/test_battle_mon_gating.py -->): stale wBattleMon (species 0, HP 15, level 6, max 21, `wIsInBattle` 1) -> `forced_faint_prompt` False, `battle_view` has no leftover numbers, `already_out` presses nothing, the `press.py` row has zeros, `event_feed` has no own mon. Loaded battle mon -> each reader unchanged (one assertion per reader). `tests/test_party_view_constants.py` <!-- new: tests/test_party_view_constants.py --> is the grep guard: read every `.py` under `src/pokeagent` except `ram_symbols.py` and the `data/` directory, assert none contains `0xD163`, `0xCC26`, `0xD057` or `0xCC2F` (case-insensitive), and none outside `ramstructs.py`, `party_view.py` and `ram_symbols.py` contains `0xD014`, `0xD015`, `0xD016`, `0xD01C`, `0xD022`, `0xD023`, `0xD024` or `0xD02D`.

## 4. What NOT to do

- Do not change any lead, fighter or slot-0 logic (`able_slot`, `fighter_slot`, `fighter_slot_of`, `menu.py:43`, `item_use.py:84`, `intervene/extra.py:42`, goals/legs/predicates HP math): the Lead directive owns them. Replacing their address literals with constants is in scope; changing what they compute is not.
- Do not edit `ram_symbols.py` or `party_view.py` beyond a missing constant; do not touch `ramstructs.active_slot`, `src/pokeagent/data/*.json`, `agentflow.toml`, protected repos, `retalk_veto.py`, `loop_veto.py`.
- Do not migrate `tools/*.py` (a later follow-up). Do not change a test's expected value to make it pass; stop and say which test instead.
- No behaviour change for a loaded battle mon or any non-stale state. No new features or dependencies. Do not run a ROM or emulator; none exists here, and do not search for one.
- No file over 600 lines; an `explorer/*.py` under 300 lines stays under 300.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
git grep -n -i -E "0xD163|0xCC26|0xD057|0xCC2F" -- src ':!src/pokeagent/data' ':!src/pokeagent/ram_symbols.py'
```
Expected: no output.

```
git grep -n -E "0xD014|0xD015|0xD016|0xD01C|0xD022|0xD023|0xD024|0xD02D|emu\.read\((0x)?[Dd]01[45]\)" -- src ':!src/pokeagent/data' ':!src/pokeagent/ram_symbols.py' ':!src/pokeagent/ramstructs.py' ':!src/pokeagent/party_view.py'
```
Expected: no output.

```
uv run pytest -q -p no:cacheprovider tests/test_ramstructs.py tests/test_magikarp.py tests/test_bandit.py tests/test_cave_topup.py tests/test_item_policies.py tests/test_ram_map.py tests/test_anomalies.py tests/test_intervene_macros.py tests/test_switch_matchup.py tests/test_intervene_lease.py tests/test_item_use.py tests/test_ram_symbols.py tests/test_party_view.py tests/test_party_view_constants.py
```
Baseline on `origin/main` for the ten files that existed on 2026-11-12 (without `tests/test_item_use.py`): `280 passed, 1 warning in 5.78s`. Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider
```
Baseline on `origin/main` (measured 2026-11-12, before the first directive): `2499 passed, 41 skipped, 1 warning in 186.93s (0:03:06)`. Re-measure on your base commit first and report it: the earlier directives add tests. Expected: that plus your new tests passed, zero failed, the same 41 skipped. About three minutes; run once at the end.

```
git status --short
```
Expected: only `src/` files named in this directive, the extended test files and the new test files.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] Both greps in section 5 print nothing. <!-- test: tests/test_party_view_constants.py -->
- [ ] With a stale wBattleMon (species 0) no reader in 3.2 uses its HP, level, moves or PP. <!-- test: tests/test_battle_mon_gating.py -->
- [ ] `tests/test_item_use.py` passes unchanged (`iu.PLAYER_MON`, `iu.MENU_ITEM` still exist).
- [ ] Full suite: zero failed, the same 41 skips.
- [ ] No `tools/`, data file, `ramstructs.active_slot` or lead/fighter logic changed.

## 8. Report

Findings first: the re-measured count from the grep in section 1, every file edited, any reader you could not gate and why (file and line), and confirmation that behaviour with a loaded battle mon is unchanged. Then both grep outputs (empty) and the tails of the two pytest commands. State plainly that no ROM was available. Name `tools/*.py` as the remaining duplicates.

## Required from User

Nothing for the build. After merge, Claude runs the ROM state tests (`tests/rom/test_party_states.py`) on the laptop to confirm the gated readers agree with real states.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/party_view.py)
- Read(src/pokeagent/ram_symbols.py)
- Read(tests/test_item_use.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-12 11:37 · agentflow-tick · none → Queued — suggested by heartbeat: Devin: mechanical, fully specified; dispatch only after Party_View_Directive merges (ram_symbols.py/party_view.py absent locally)
<!-- queue:end -->
