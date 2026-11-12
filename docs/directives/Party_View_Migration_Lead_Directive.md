# Trailswarm: move the slot-0 lead and fighter readers onto PartyView, with every dependent pinned by a test

**Size:** M. **Assignee:** devin.

**Depends on:** `Party_View_Directive.md` AND `Party_View_Migration_Constants_Directive.md` merged (they touch the same files: `bring_out.py`, `item_use.py`, `goals.py`, `legs/states.py`, `press_track.py`, `ram_event_kinds.py`, `interaction_types.py`, `campaign.py`). Work on top of both. If `src/pokeagent/ram_symbols.py` or `src/pokeagent/party_view.py` is missing, stop and say so in the PR description.

## Why this is a separate directive (the split decision)

This is the judgement half of the migration: about 15 readers whose logic changes from "slot 0 is the lead" to the view's lead / fighter rule, each with dependents that need a pinning test. The constants sweep and the stale-battle gating are the Constants directive's.

## 1. Why this exists

Audit 2026-11-12, re-verified on `origin/main` (#206 `retreat_heal` has merged). When the lead has fainted and a second mon is alive, these readers still act on slot 0:

- `explorer/behaviours/bring_out.py` `able_slot` (lines ~15-21): hand-computes party HP with `PARTY_HP + MON_STRIDE * i`, species from `PARTY_SPECIES + i`.
- `explorer/behaviours/cave_topup.py` `fighter_slot` (lines 28-35): slot 0 unless a Magikarp is present. Dependents: `explorer/behaviours/retreat_heal.py:45` (`lead_mon = party[min(fighter_slot(ctx.emu), len(party) - 1)]`) and `:71` (`assess(party, ..., fighter_slot(ctx.emu...`), added by #206; `tests/test_retreat_heal.py::test_fainted_lead_with_a_healthy_second_is_judged_on_the_second` already pins one case.
- `explorer/item_policies/view.py` `fighter_slot_of(party: list[Mon])` (lines 30-38): "slot 0 without a Magikarp, else the strongest non-Magikarp"; works on plain `Mon` data. Dependents: `item_policies/rare_candy.py:17`, `item_policies/vitamins.py:17`, `item_policies/hm_teach.py:92-93` (`_fighter`, used at lines 60 and 105). Existing tests: `tests/test_item_policies.py::test_fighter_slot_follows_the_trainee_rule`, `test_vitamin_goes_to_the_fighter_at_once`, `test_candy_for_a_long_grind_and_never_a_magikarp`, `test_hm_learner_prefers_a_free_slot_then_a_non_fighter`.
- `explorer/item_policies/policy.py:61`: `rare_candy.atlas_minutes(atlas, party[0].name, goal, party[0].level, ...)`.
- `explorer/item_policies/xitems_battle.py:33`: `best_move(party[0], boss[0], default_chart(), moves)` where `party = [c for c in our_party(ctx.emu) if c.name != "MAGIKARP"]`.
- `explorer/behaviours/menu.py:43`: `ctx.emu.read(0xD173 + i)` (slot 0's moves) in the "learn a move" prompt.
- `explorer/behaviours/item_use.py:84`: `slot = emu.read(PLAYER_MON) if party_target is None else party_target` (raw wPlayerMonNumber; the comment says it is stale outside a fight).
- `intervene/extra.py:42`: `party, slot = read_party(emu), emu.read(PLAYER_MON)` in `_our_mon` (raw wPlayerMonNumber, used when wBattleMon reads species 0).
- `goals.py:51-56` (all-party-full-HP, reads `0xD16C + 0x2C * i`), `legs/states.py:29` (`calm`: lead HP above half), `procedures/predicates.py:80-96` (lead HP / max HP), `explorer/press_track.py:49,73` (`read(0xD18C)`, lead level), `campaign.py:96,121` (`0xD163`, `0xD173` party moves).

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

1. `bring_out.able_slot`, `cave_topup.fighter_slot`, `item_policies/view.fighter_slot_of`, with the dependents' pinning tests (3.2).
2. `policy.py:61`, `xitems_battle.py:33`, `menu.py:43`, `item_use.py:84`, `intervene/extra.py:42`.
3. `goals.py`, `legs/states.py`, `procedures/predicates.py`, `press_track.py`, `campaign.py`.
4. Tests.

## 3. The work

**3.1 Rules.** Healthy lead and no Magikarp: behaviour is unchanged. Only the fainted-lead case changes. No emergency may be lost (`Party_View_Directive.md` section 3.3b): "a member fainted" must keep triggering what it did.

**3.2 Moves.**
- `bring_out.able_slot(emu)`: from `read_party_view`: alive = not fainted; the first alive non-MAGIKARP (`SPECIES_MAGIKARP`), else the first alive, else None.
- `cave_topup.fighter_slot(emu)`: `view.fighter().index`, 0 for an empty party (as today). Update its docstring. Its dependents are pinned by tests: in `tests/test_retreat_heal.py` add `test_retreat_heal_uses_the_fighter_slot_with_a_magikarp_lead` (Magikarp in slot 0, strong mon in slot 1: `lead_mon` is slot 1's) next to the existing fainted-lead test.
- `view.fighter_slot_of(party: list[Mon])`: plain data, so it cannot call the view. Lead rule on `Mon`s: no MAGIKARP -> the first non-fainted `Mon`'s slot, slot 0 if all fainted; with a Magikarp: unchanged (strongest non-Magikarp by `(hp > 0, level, hp)`, `None` if only Magikarps). Keep the signature. Add, in `tests/test_item_policies.py`, `test_fighter_slot_of_skips_a_fainted_lead`, `test_vitamin_goes_to_the_second_when_the_lead_fainted`, `test_candy_goes_to_the_second_when_the_lead_fainted` and `test_hm_teach_fighter_is_the_second_when_the_lead_fainted` (these exercise `vitamins`, `rare_candy` and `hm_teach` through `fighter_slot_of`).
- `policy.py:61` and `xitems_battle.py:33`: index the same list by the fighter's slot instead of `party[0]` (for `xitems_battle`: the first non-fainted entry of the Magikarp-filtered `party`, else `party[0]`). Do not change which move or item is picked for a healthy lead.
- `menu.py:43`: the current moves of the mon that is learning are not on screen; use `read_party_view(emu).fighter()`'s `moves` (names via `ROM_KB`, as the line does today).
- `item_use.py:84`: `slot = party_target` if given; else `view.active_slot` if not None; else `view.fighter().index` if `view.fighter()` is not None; else (empty party view) the raw `wPlayerMonNumber` read, exactly as today, so `tests/test_item_use.py::test_battle_menu_navigation_and_party_pick` (which sets only `iu.PLAYER_MON` = 2 with no party bytes) keeps passing. Guard `view.fighter() is None` explicitly; never index into it. Keep the `PLAYER_MON` and `MENU_ITEM` names (the Constants directive left them; `tests/test_item_use.py:47` uses them).
- `intervene/extra.py:42` (`_our_mon`): when wBattleMon reads species 0, use `read_party_view(emu).active_slot` (verified), else `.fighter()`; if both are None fall back to `_mon(me)` as the code does when `slot >= len(party)`. Delete the raw `PLAYER_MON` read there. The existing intervene tests in `tests/test_intervene_lease.py` and `tests/test_intervene_macros.py` must keep passing.
- `goals.py`, `legs/states.py`, `procedures/predicates.py`: "party at full HP" uses `read_party_view(...).slots`. `legs/states.calm` stays False when any member has fainted (`not view.any_fainted and fighter HP above half`); the `predicates` health checks use `any_fainted or fighter HP low`, as `perceive.party_needs_heal` does.
- `press_track.py:49,73`: the level read uses `perceive.true_lead_level(emu)`.
- `campaign.py:96,121`: party-move checks use `PartySlot.moves` for every slot (the check already iterates slots); party count from `ram_symbols`.

**3.3 Tests.** In the existing files, FakeEmulator style: one test per moved reader with a fainted lead plus a live second mon (it acts on slot 1), and one healthy-lead assertion each. `tests/test_party_view_lead.py` <!-- new: tests/test_party_view_lead.py --> pins that `cave_topup.fighter_slot`, `view.fighter_slot_of` and `magikarp.fighter` return the same slot for six hand-built parties (healthy, fainted lead, Magikarp lead, Magikarp second, all fainted, single mon), and that `item_use` with an empty party view and no `party_target` still returns the raw-slot press.

## 4. What NOT to do

- Do not change address constants or species gating (the Constants directive's); do not edit `ram_symbols.py` or `party_view.py` beyond a missing item; do not touch `ramstructs.active_slot`, `data/*.json`, `agentflow.toml`, protected repos, `retalk_veto.py`, `loop_veto.py`, `tools/*.py`.
- Do not change behaviour for a healthy lead, a loaded battle mon or a non-Magikarp party.
- Do not change a test's expected value to make it pass; stop and say which test instead. No new features or dependencies. No ROM or emulator (none here; do not search).
- No file over 600 lines.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_ramstructs.py tests/test_magikarp.py tests/test_bandit.py tests/test_cave_topup.py tests/test_item_policies.py tests/test_ram_map.py tests/test_anomalies.py tests/test_intervene_macros.py tests/test_switch_matchup.py tests/test_intervene_lease.py tests/test_item_use.py tests/test_retreat_heal.py tests/test_party_view.py tests/test_party_view_lead.py
```
Baseline on `origin/main` for the ten files that existed on 2026-11-12 (without `tests/test_item_use.py` and `tests/test_retreat_heal.py`): `280 passed, 1 warning in 5.78s`. Expected: all pass, none skipped.

Search with your built-in file search tool (Grep), NOT a shell `git grep` (not on the Devin allow list), for the regex `emu\.read\(PLAYER_MON\)|read\(PLAYER_MON_NUMBER\)` over `src/`.
Expected: the only match is the empty-party fallback in `behaviours/item_use.py`.

```
uv run pytest -q -p no:cacheprovider
```
Baseline on `origin/main` (measured 2026-11-12, before the first directive): `2499 passed, 41 skipped, 1 warning in 186.93s (0:03:06)`. Re-measure on your base commit first and report it: the earlier directives add tests. Expected: that plus your new tests passed, zero failed, the same 41 skipped. About three minutes; run once at the end.

```
git status --short
```
Expected: only `src/` files named in this directive and test files.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here; if something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only. Do not use bare `python`.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file, and do not write a `## Queue` block.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] With a fainted lead and a live second mon, `able_slot`, `fighter_slot`, `fighter_slot_of` (and through it `rare_candy`, `vitamins`, `hm_teach`), `retreat_heal`, `policy.py`, `xitems_battle`, `menu.py`, `item_use`, `intervene/extra._our_mon`, the goals full-HP check and `legs/states.calm` act on slot 1 or do not call the party healthy. <!-- test: tests/test_party_view_lead.py -->
- [ ] `cave_topup.fighter_slot`, `fighter_slot_of` and `magikarp.fighter` agree on six pinned parties. <!-- test: tests/test_party_view_lead.py -->
- [ ] `item_use` guards `view.fighter() is None`; `tests/test_item_use.py` passes unchanged.
- [ ] Full suite: zero failed, the same 41 skips.
- [ ] Healthy-lead behaviour unchanged; no constants, gating, `tools/` or data file changed.

## 8. Report

Findings first: every reader moved, any left and why (file and line), and any place a healthy-path result changed (must be none). Then the grep and the pytest tails. State plainly that no ROM was available and the real-state confirmation is the controller's (`Party_RAM_State_Tests_Directive.md` states).

## Required from User

Nothing for the build. After merge, Claude runs the ROM state tests and a hands-off check (`tools/hands_off_check.py`) on the laptop to confirm healthy-lead behaviour is unchanged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/party_view.py)
- Read(src/pokeagent/ram_symbols.py)
- Read(tests/test_item_use.py)
- Read(tests/test_retreat_heal.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-party-view-migration-lead-directive |
| Base branch | - |
| Base commit | acf275e60ceb6a4988e9326594ecb9d36066f9e4 |

**Status log**
- 2026-11-12 11:38 · agentflow-tick · none → Queued — suggested by heartbeat: Devin: fully specified migration; dispatch only after Party_View and Party_View_Migration_Constants both merge
- 2026-11-12 16:04 · robert-claude-laptop · Queued → Approved
- 2026-11-12 17:29 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-party-view-migration-lead-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M78Y28H82VE8YJD8PX91CBZ3
- 2026-11-12 17:39 · dispatcher · launched pid=14620; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-party-view-migration-lead-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (8 declared need(s); 4 external))
<!-- queue:end -->
