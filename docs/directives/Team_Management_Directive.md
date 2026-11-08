# PokeAgent: team management - the gate judges the whole team, the lead is chosen by matchup, switches follow type and HP, exp is spread by a level band, and grinding priority rises with team size

## Why this exists

Robert, 2026-11-07 night, watching the marathon run (explore-20261107-191457-26240): "It also doesn't understand
correct team management, so that needs to be improved, as the team grows, exploit the available options. grinding
becomes more important." and "Marathon is also failing to recognize that it's not strong enough for Misty."

Measured facts (inventory 2026-11-07 on main after PRs #157 and #158; file:line cited):

- **The training gate reads slot 0 only.** `perceive.py:38-44` `lead_level` = RAM 0xD18C (party slot 0 level) when
  no Magikarp trainee; `plan_goal.py:102` `training_live = 0 < lead_level < need`; `training.py:82-88` `under_level`
  compares `party[0].level`; `knowledge/readiness.py:143-145` `required` raises only `party[0]` to find the level
  answer, while `fight` (:99-121) scores the WHOLE party (best switch-in each turn). In the run, at step 22,911 the
  party was `[133 L12, 109 L8, 178 L23 (Charmeleon), 169 L10, 142 L12, 107 L9]`: the strong mon sat in slot 3 and an
  L12 led. The agent fought MISTY at steps 27,361 and 27,871 and blacked out both times; the gym trainers before that
  left 3 of 6 members at 0 HP.
- **Party order only places the Magikarp trainee.** `behaviours/party_order.py` (82 lines) `trainee_home()` :29-32 puts
  the trainee in slot 0 outside dungeons and last inside `DUNGEON_MAPS`; it ranks nothing by stats or type.
- **Switching is trainee-only.** `behaviours/switch_out.py` (117 lines) applies only with `ctx.switch_train` or the
  trainee out; `magikarp.py:88-98` `switch_candidate` picks the healthy (HP >= `SWITCH_MIN_HP` 0.25) non-trainee with
  the highest (level, hp); no type matchup. Move choice (`explorer/battle.py:134-156` `move_scores` = power x type
  effectiveness x STAB 1.5 x accuracy; `battle_moves.py:101-119`) is the only place type matters in battle.
  `knowledge/damage.py:20-26` `expected_damage` (Gen 1 formula, AVG_ROLL 0.925, CRIT_RATE 0.06) and
  `readiness.best_move`/`fight` already simulate matchups for planning.
- **No exp-spread planner.** The only rotation is the Magikarp swap (switch on turn one, bring in the highest-level
  healthy member). Related constants: `TEAM_GAP = 6` (readiness.py:20), `CATCHER_BAND = 6` (knowledge/catcher.py:19),
  `RISK_LEVEL_MARGIN = 4` (catch_plan.py:29), grind `BAND = 4` (grind/observed.py:12). `explorer/grind.py`
  GrindBudget (GRIND_BATTLES 25, GRIND_STEPS 2500, GRIND_BLACKOUTS 2, CEILING_MARGIN 6) lifts the gate after a budget
  (`plan_goal.py:155-168`; gate lifted = need 0).
- **No PC / box code.** grep finds no deposit/withdraw; `dialog.py:10` answers NO to prompts containing "deposit",
  "release", "toss", "nickname"; `catch_plan.py:80-81` returns no actions at `TEAM_SIZE = 6`, so `team_hunt` stops
  applying; what Catch does when the game offers the box at 6 is unverified.
- **Gym need is computed for one mon.** `tools/grind_report.py:42-52` `need_levels` uses `trainer_mon(sp, 5, kb)` and
  `required_level(goals, 0, [c])`; the atlas `inputs.need` is a single starter at L5 (CHARMANDER {brock 17, misty 25,
  surge 36}).
- **Items.** Potions in battle `battle.py:178-189`; X items `item_policies/xitems.py` (trainer battles only, one per
  battle, readiness score band THIN_LOW/THIN_HIGH -0.15/0.45); Rare Candy `item_policies/rare_candy.py`.
- Sizes: party_order.py 82, switch_out.py 117, magikarp.py 124, battle_moves.py 154, battle.py 289, plan_goal.py 168,
  training.py 126, readiness.py 226, team_value.py 224, catch_plan.py 122, team_hunt.py 179, `explorer/context.py` 299,
  `explorer/memory.py` 299 (ceiling 300, `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size`).

Read first: the files above; `docs/directives/Team_Builder_V2_Directive.md`, `Catch_Methods_Directive.md`,
`Team_Readiness_Directive.md`, `Trainer_Ledger_And_Battle_Avoidance_Directive.md`, `Grind_Points_Directive.md`
(queued in parallel: it owns grind SPOT selection; this directive owns WHO trains and WHEN grinding outranks the
plan); `docs/KNOWLEDGE.md` sections on readiness and the Gen 1 exp split.

## Scope (in this order)

1. `src/pokeagent/knowledge/team_plan.py` (new, pure, under 300 lines): team-level judgments.
2. Gate on the team, not slot 0: `training.under_level`/`required_level` and `plan_goal` use `team_plan`.
3. Lead choice by matchup: `party_order` places the planned lead (not only the trainee) before a known boss / route.
4. Matchup switching in battle: `switch_out` gains a type/HP-driven switch for trainer battles.
5. Exp spread: a level-band target per member and a rotation policy that keeps the band.
6. Grinding priority: a `grind_pressure` signal that rises with team size and the gap to the next boss, consumed by
   `plan_goal` to prefer a grind episode (Grind_Points) over pushing the stage.
7. Party-full policy: what Catch does at 6 members (box prompt) is decided, logged, and tested.
8. Tests, `tools/grind_report.py` need-per-team, KNOWLEDGE.md.

## The work

### 1. `knowledge/team_plan.py`

- `TeamView` from the party (list of `Combatant`-like members with species, level, types, moves, hp, max_hp): pure
  input, no emulator.
- `boss_need(team, boss, kb) -> Need(level_by_slot, team_score, lead_slot, weak_slots)`: run `readiness.fight` for
  the whole team as today, then compute per-member `required` by raising EACH member in turn (not only `party[0]`)
  and report the minimum team change that makes `fight` pass: either "raise slot k to L" or "no single raise works:
  train the band". Keep `readiness.py` untouched; call its functions.
- `choose_lead(team, opponent_party, kb) -> slot`: the member with the best first-turn matchup (`best_move` damage
  ratio against the opponent's lead, then HP fraction, then level); ties by slot. For wild grinding the lead is the
  trainee (existing behaviour); for a known trainer/boss it is this choice.
- `switch_choice(team, active_slot, opponent, kb) -> slot | None`: in a TRAINER battle, if the active member is
  "thin" (expected incoming damage over `SWITCH_HP_TURNS = 2` turns >= its HP, or its best move does `<= WEAK_RATIO
  0.5` of the opponent's HP per turn) and another healthy member (HP >= `SWITCH_MIN_HP` 0.25) has a strictly better
  matchup (ratio improvement >= `SWITCH_GAIN = 1.5`), return it; else None. Never switch the trainee IN; never switch
  more than `MAX_SWITCHES_PER_BATTLE = 2` times (state lives in the battle record, not context).
- `level_band(team, need) -> dict[slot, (lo, hi)]`: target band per member: lead at `need`, others within `BAND_BELOW
  = 4` of the lead (constant, untuned, named); `band_breakers(team, band)` lists members below their lo.
- `grind_pressure(team, need, next_boss_gap_steps, blackouts_recent) -> float` in [0, 1]: rises with (a) the number
  of band breakers over team size, (b) `need - lead_level`, (c) recent blackouts; 0 when the team passes `boss_need`.
  Document the formula in the docstring; it is the one knob `plan_goal` reads.

### 2. The gate judges the team

- `training.required_level` / `under_level` take the whole party and use `team_plan.boss_need`: the gate is "under"
  when `team_score` fails, regardless of which slot holds the strong mon. `perceive.lead_level` stays for logging.
- `plan_goal.py`: log the verdict once per change as today (`readiness_note`), now including `lead_slot` and
  `weak_slots`; when the verdict is "not ready" and a planner stage would enter a gym map
  (`knowledge/trainers.GYM_BOSSES` map ids), do NOT enter: return the training/grind decision instead. Also feed the
  leader's placement into the sight-line avoidance from PR #158 (`trainer_hooks.avoid_pass` / `trainer_route.block_sight`)
  with plan "avoid" while not ready, so frontier cannot walk into the leader. (The sight tiles themselves are a
  separate directive; use the existing SIGHT_GUESS mechanics.)

### 3. Lead by matchup

- `party_order.py`: before a known trainer target (trainer ledger next target) or a boss stage, reorder so
  `choose_lead` is slot 0 (reuse `party_menu.reorder_press`, `MAX_PRESSES`, `RETRY_AFTER_STEPS`); keep the Magikarp
  rule (trainee last in dungeons). One reorder per target change; log the reason.

### 4. Matchup switching

- `switch_out.py`: a second trigger alongside the trainee path: in a trainer battle with `switch_choice` != None,
  press the switch (`switch_press`) once per decision, with the existing `MAX_PRESSES` cap, logged as
  `switch_matchup: <who> -> <target> (<reason>)`. Keep `switch_out.py` under 300 lines: if it grows past, move the
  trainee path into `switch_train.py` and keep `switch_out.py` as the dispatcher.

### 5. Exp spread

- A `rotation` policy: outside boss/trainer fights (wild battles on a grind), the lead is the lowest band breaker
  that can survive the wild mon (reuse `catcher.qualifies` style damage checks), swapped out after the first turn to
  the strongest member as the Magikarp swap does today, so the breaker earns the Gen 1 shared exp. Implement by
  generalising the trainee selection (`magikarp.trainee_slot_for` -> `team_plan.trainee_slot`) rather than adding a
  second mechanism.

### 6. Grinding priority

- `plan_goal.py` reads `grind_pressure`; above `GRIND_PRESSURE_START = 0.5` it starts a grind episode (Grind_Points'
  `grind_episode.start`, or until that lands, `train_route`) instead of pushing the stage; below
  `GRIND_PRESSURE_STOP = 0.2` it releases. Hysteresis constants named and untuned. The GrindBudget caps still apply.

### 7. Party full

- Decide and implement: at 6 members, when a wanted species (catch plan) appears, Catch throws only if the catch plan
  marks a member as `release_candidate` (lowest `team_value`, not the trainee, not a Cut learner the run needs); the
  box prompt is answered YES in that case (dialog.py rule) and the deposit is logged in the dossier; otherwise the
  policy returns `skip` with reason "party full". No PC withdraw in this directive.

### 8. Tests, report, docs

- `tests/test_team_plan.py`: boss_need on the marathon party fixture (slot 3 strong) says "not ready for Misty" and
  names slot 3 as the lead; choose_lead picks the Water-resistant member against Misty's Staryu; switch_choice
  switches a thin Fire lead vs Water for a Grass/Electric member when present and returns None when nothing is
  better; level_band and band_breakers; grind_pressure monotonic in gap and breakers.
- `tests/test_party_order_matchup.py`, `tests/test_switch_matchup.py`, `tests/test_grind_pressure_plan_goal.py`
  (synthetic contexts, labelled synthetic), `tests/test_party_full_policy.py`.
- `tools/grind_report.py` `need_levels`: use `team_plan.boss_need` over a representative team (starter + the catch
  plan's early catches) and print both the single-mon and team needs.
- `docs/KNOWLEDGE.md`: "Team management" paragraph (gate on the team, lead by matchup, switch rule, band, pressure).

## What NOT to do

- Do not edit `planner*.py`, `ship_gate.py`, `knowledge/readiness.py` internals (call them), `heal_walk.py`,
  `trainer_ledger.py` internals.
- Do not add fields to `explorer/context.py` or `explorer/memory.py` (both at 299): state goes in a `team_plan.of(ctx)`
  dict on `ctx.__dict__` like `status_care.of(ctx)`.
- Do not tune constants to the marathon run; name them, mark them untuned.
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree; if a named file is
  missing, stop and say so in the Status row.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_team_plan.py tests/test_party_order_matchup.py tests/test_switch_matchup.py tests/test_grind_pressure_plan_goal.py tests/test_party_full_policy.py tests/test_explorer_behaviours.py tests/test_team_readiness.py tests/test_team_value.py tests/test_catch_plan.py tests/test_team_hunt.py tests/test_catch_seam.py tests/test_catch_policy.py
```
Expected: all pass; the Team Builder V2 and Catch tests are unedited.

```
uv run pytest -q
```
Expected tail: ~1905+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/knowledge/team_plan.py src/pokeagent/explorer/behaviours/party_order.py src/pokeagent/explorer/behaviours/switch_out.py src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/training.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
```
Expected: each under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory.
- Branch only; commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- The gate is team-level and the marathon fixture is judged "not ready for Misty" with slot 3 as lead; the agent
  does not enter a gym map while not ready; matchup switch and lead choice exist and are tested; band + pressure
  exist and `plan_goal` consumes them; party-full policy decided and tested; suites green; sizes under 300.
- Status row set to Review with head sha, diff stat, wc -l line, test tails.

## Report

Diff stat, test tails, wc -l line, constants chosen and why, and the controller validation list (a headless run from
`baselines/` Cerulean state must not enter the gym with the marathon party; a Pidgey-vs-Water fixture switch).

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-team-management-directive |
| Base branch | - |
| Base commit | d18e5b2b5db20bfac3dfdac7d14c85106640c60f |
| Head commit | e6c8965f9ed7ecb5320571d392533febbe8f2dd6 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 20:37 · robert-claude-laptop · none → Queued — Claude 2026-11-07 from Robert: team management must exploit the growing team; gate judges slot 0 only (marathon entered Misty's gym with the strong mon in slot 3)
- 2026-11-07 20:38 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives (greenfield modules); Robert asked for this tonight
- 2026-11-07 20:38 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-team-management-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6WCY1B8X0SH90CS62PWX8YM
- 2026-11-07 20:46 · dispatcher · launched pid=6388; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-team-management-directive; provisioned: uv sync --frozen
- 2026-11-07 21:10 · devin · In progress → Review — head 7a0363c22d7eb77790d9530753a009692aa0166b. diff: 16 files, +1034/-52 (new src/pokeagent/knowledge/team_plan.py + 5 test files; touched training, plan_goal, party_order, switch_out, magikarp, catch, menu, dialog, grind_report, KNOWLEDGE.md). wc -l: team_plan.py 244, party_order.py 132, switch_out.py 197, plan_goal.py 251, training.py 152, context.py 299, memory.py 299 - all under 300. Tests: targeted 12-file set 116 passed; full suite 1892 passed, 40 skipped (ROM-gated), 0 failed. [origin] spent: devin 24 min est. n/a
<!-- queue:end -->
