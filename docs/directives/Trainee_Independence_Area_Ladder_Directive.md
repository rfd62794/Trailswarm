# PokeAgent: Trainee independence and the area ladder - release a trainee to fight alone as soon as it can, and pick each stage's grind map by expected XP per step instead of a hard pin to Route 1

**Size:** L. **Model:** swe-2-high. **Assignee:** devin.

**Depends on `Level_Banded_Grind_Directive.md` merged.** It adds `src/pokeagent/grind/solo_viable.py` <!-- new: src/pokeagent/grind/solo_viable.py --> (`is_solo_viable(trainee, kb, map_id)`, `solo_verdict`, `encounter_mix`, `SOLO_MIN_WIN`, `SOLO_MARGIN`) and the `ep["solo"]` hook in `switch_out.trainee_out`. Check with `git ls-files src/pokeagent/grind/solo_viable.py`. If it prints nothing, STOP and write "Level_Banded_Grind not merged" in the Status row; do not recreate it. This directive reuses that estimator and generalises its fight-mode hook from "a grind episode is live" to "any training, including the `train_route` path"; it does not redo it.

**Independent of the Training Controller slice 5b / shadow-to-live switch** (see section 1.3): do not touch `training_ctl/{adapters,controller,state,exit_rule,sustain,target}.py`, `grind.py` (GrindBudget, stall_hold_holds), `area_grind.py`, or `grind_episode._end_reason`.

**Read first (all in the worktree; if one is missing, stop and say so in the Status row; do not search):** `src/pokeagent/explorer/train_target.py`, `src/pokeagent/grind/stage_maps.py`, `src/pokeagent/grind/atlas.py` (`Spot`, `rank_spots`, `prior_xp`), `src/pokeagent/grind/solo_viable.py` (after Level_Banded), `src/pokeagent/explorer/training_ctl/roster.py`, `src/pokeagent/explorer/behaviours/switch_out.py` (lines 31-45, 134-150), `src/pokeagent/explorer/behaviours/plan_goal.py` (lines 233-241 only), `src/pokeagent/explorer/behaviours/battle.py` (around line 263), `src/pokeagent/knowledge/encounters.py`, `src/pokeagent/knowledge/team_floor.py`, `tests/test_train_target.py`, `tests/test_training_ctl_roster.py`, `tests/test_training_ctl_target.py`, `tests/test_switch_matchup.py`.

## 1. Why this exists

Robert, 2026-11-15 (verbatim): "we need to explore training in further areas to gain more exp once we pass certain floors with the lead, as well as improving the ability to detect when a trainee is strong enough to stand on their own in the weaker areas. I think we would make quicker progress if we let the Trainee stand on their own as soon as they can."

### 1.1 Measured (real ROM, Claude, 2026-11-15; main 2346256, Bulbasaur, flags `--bandit --par-follow --adaptive-pace --fast-text --novelty --save-leg-states`, train_level 8)

Goal frames: deliver_parcel step 1144 -> to_route2 step 11600 -> to_pewter 12055 -> to_gym 12121 -> beat_brock 12251. So steps 1144 to 11600 (10,456, about 85% of all steps to Brock) are training; once the party left Route 1 it took 651 steps to Brock.

- All 243 battle_ends in that window were on map 12 (Route 1). Party at step 1277: Bulbasaur (internal 153) L8 alone. At step 11509: Rattata (165) L11, Pidgey (36) L12, Bulbasaur L14.
- Why Route 1: `train_target.stage_target` returns `TRAIN_MAP["beat_brock"]` = 0x0C whenever `stage_maps.allowed(stage)` is set, and `plan_goal._grind_step` passes the same `TRAIN_MAP[ctx.stage_goal]` to `train_route.step`. The gate holds (readiness log: "team not ready vs BROCK: lead needs L13"; "team floor for beat_brock: need 2 members >= L12, have 0"; grind latch on at pressure 0.50), so the run grinds on the pinned map until BOTH the sim need (L13, +0.30 blackout margin) and the floor (2 members at L12) are met.
- XP by member over steps 1144-11700 (`xp_rates.jsonl` windows): Bulbasaur 1298 xp in 103 battles, 96 of them `switched` (lead sent in first, then swapped out for a trainee: the switch trick, 6 presses each); Rattata 1321 xp in 87 battles, all `solo`; Pidgey 742 xp in 51 battles, all `solo`. Total about 3,360 xp in 10,000 steps = 336 xp per 1,000 steps, 14 xp per battle. The lead (already past the L12 floor, needing L13) took 43% of the battles.
- Encounter tables of the maps a pre-Brock stage may use (ROM-drained, `wild_by_map`; ids: 12 = 0x0C Route 1, 13 = 0x0D Route 2, 33 = 0x21 Route 22, 51 = 0x33 Viridian Forest, 14 = 0x0E Route 3): Route 1 L2-5 Pidgey/Rattata, grass_rate 25; Route 2 L2-5 Rattata/Pidgey/Weedle, rate 25; Route 22 L2-5 Rattata/Nidoran/Spearow, rate 25; Viridian Forest L3-6 Caterpie/Weedle/Kakuna/Metapod/Pikachu, rate 8; Route 3 L3-8, rate 20 (beyond the Pewter guard: not allowed before Brock). **So pre-Brock wild XP per fight is nearly the same on Routes 1, 2 and 22 and the Forest has a third of the encounters per step. Moving to a "higher" map does not by itself buy XP before Brock; do not assume it does.** The gain pre-Brock comes from (a) full XP for a trainee that fights alone (no switch trick, no sharing with a lead that is already over its need), and (b) the ladder picking by measured/predicted XP per step, including one-time trainers, with the stage's real choices (Route 3 / Mt Moon for `to_mt_moon`, Route 24/25 for `beat_misty`) where the wild levels do differ a lot (Route 4 is L6-12).
- Shadow controller, `marathon_20261115_1154.err`: 70 `training_ctl shadow mismatch` lines (23 floor_unmet, 24 train_member, 23 train_route_live), every one old=True/0 vs shadow=False/None. Unverified hypothesis (section 4.5): `adapters.derived` reads the party as `[]` while `ctx.view.battling`, so `team_for/floor_for` return None and the shadow reads "done". This is a measurement artifact until proven otherwise, not evidence that the new controller is right.

### 1.2 The three changes

1. **Area ladder.** The map a stage trains on is chosen, not pinned: rank the stage's allowed maps (`stage_maps.allowed`, extended where a stage has none) by expected XP per step for the member being trained, from the same `atlas.rank_spots` the ledger already feeds, restricted to maps the agent has a learned route to (`training_ctl.target.known`), with hysteresis so it does not ping-pong.
2. **Trainee release.** One per-member verdict "can stand alone on map M": the ROM-math estimate (`solo_viable.is_solo_viable`) AND observed solo results on that map. While released, the trainee leads and stays in (no switch trick), and the lead is not escorted along for the ride. Released as early as the estimate allows (probation), revoked on a faint, a blackout, or a low-HP fight.
3. **Safety floors unchanged.** The per-checkpoint team floor (`team_floor.FLOOR_BY_GOAL`, 2 members) and the whole-team boss readiness (`team_plan.boss_need`, the gym hold) are NOT touched (Robert, 2026-11-12). This changes how training is reached and who fights, never the gate. It must not raise blackouts.

### 1.3 Overlap with the Training Controller and the Curriculum (checked 2026-11-15)

- Slices 1-5a are merged (`training_ctl/{state,controller,adapters,target,sustain,roster,exit_rule}.py`). The controller is still a SHADOW: `controller.observe` logs mismatches and writes nothing; the live flags remain `plan_goal`/`grind_episode`/`train_target`. Slice 5b (fold GrindBudget, stall_hold_holds, gate_lifted into one exit rule) and the later shadow-to-live switch are NOT built and not required here. This directive extends the OLD, live path through the modules slices 2 and 4 already made the single owners (`train_target`, `training_ctl/target.py` `known`/`choose`, `training_ctl/roster.py`), so when the live switch happens the ladder and release rule move with them. Add nothing to `TrainingState`; if a test needs the shadow to agree, stop and report.
- `Level_Banded_Grind_Directive.md` (Queued, not built) is the prerequisite: it owns `solo_viable` and the episode-only fight-mode hook. This directive makes the hook apply to the `train_route` path too (where the measured 96 switched battles happened) and adds the observed-results half of the verdict.
- `Training_Readiness_Edge_Cases_Directive.md` (Queued) tests `roster.py`; if it merges first, rebase and keep both.
- `Curriculum_Build_Selection_Directive.md` (Review) picks a start state by team build in `tools/seg_sched.py`; no shared code, no conflict. A faster Brock leg changes the build library's timings, nothing else.

## 2. Scope (files, in order)

New modules (each under 120 lines, each with its own test file):

1. `src/pokeagent/grind/area_ladder.py` <!-- new: src/pokeagent/grind/area_ladder.py --> (pure; imports only `grind.*`; no `explorer` import): the pick and the hysteresis (3.1).
2. `src/pokeagent/explorer/training_ctl/release.py` <!-- new: src/pokeagent/explorer/training_ctl/release.py --> : the per-member release state (3.2).

May change (and only by the listed amount; report `wc -l` before and after):
- `src/pokeagent/grind/stage_maps.py` (13): a `LADDER_BY_STAGE` for stages without an allow-list (3.1); `PRE_BROCK` and `BY_STAGE` unchanged.
- `src/pokeagent/explorer/train_target.py` (39; at most +15): `stage_target` asks the ladder.
- `src/pokeagent/explorer/behaviours/plan_goal.py` (298; ceiling 300, net 0 lines): line 239 uses `train_target.stage_target(ctx)` instead of `TRAIN_MAP[ctx.stage_goal]`.
- `src/pokeagent/explorer/training_ctl/roster.py` (38; at most +10): `released(ctx, slot)`.
- `src/pokeagent/explorer/behaviours/switch_out.py` (232 after Level_Banded; at most +6): `trainee_out` also stays in when the roster says the slot is released.
- `src/pokeagent/explorer/behaviours/battle.py` (at most +3): feed each wild battle's result to `release.note_battle` at the line that calls `record_battle_result` (around 263).

No other file. `explorer/context.py` is at 300: do not touch it; keep state in `ctx.__dict__` like `exit_rule` does.

## 3. The work

### Current code (verified on main 2346256, 2026-11-15; the merged files win)

```python
# src/pokeagent/explorer/train_target.py
TRAIN_MAP imported from knowledge.encounters:  {"beat_brock": 0x0C, "to_mt_moon": 0x0E, "beat_misty": 0x23}
def stage_target(ctx) -> int:
    stage = getattr(ctx, "stage_goal", None)
    return TRAIN_MAP[stage] if stage_maps.allowed(stage) and stage in TRAIN_MAP else ROUTE24
def only_maps(ctx):   # narrows a NEW episode to {stage_target} while train_route_live
# src/pokeagent/explorer/behaviours/plan_goal.py:239  (_grind_step)
kw = {"target": TRAIN_MAP[ctx.stage_goal]} if stage_maps.allowed(ctx.stage_goal) else {}
# src/pokeagent/grind/stage_maps.py
PRE_BROCK = frozenset({0x0C, 0x0D, 0x21, 0x33});  BY_STAGE = {"beat_brock": PRE_BROCK}
# src/pokeagent/explorer/training_ctl/target.py
def known(ctx, point) -> bool   # map visited AND a learned route reaches it (travel_steps < FAR_TRAVEL)
# src/pokeagent/explorer/training_ctl/roster.py
def trainee_slot(ctx, *, breakers=False) -> int | None
# src/pokeagent/knowledge/team_floor.py: FLOOR_BY_GOAL = {"beat_brock": 12, "beat_misty": 19, ...}; TEAM_FLOOR_MEMBERS = 2
# src/pokeagent/grind/atlas.py: rank_spots(starter, level, need_level, tables, stats, center_cost, growth, candidates=None, top=3, names=None) -> [Spot]
#   Spot has map_id, xp_per_step, win, blackout, travel_steps, steps_to_goal (None without need_level)
#   tables = {"wild": kb["wild_by_map"], "base_exp": {name: row["base_exp"] for row in kb["species_by_dex"].values()}}  (see src/pokeagent/grind/refresh.py:69)
```

### 3.1 `grind/area_ladder.py`: pick a rung, with hysteresis

```python
SWITCH_GAIN = 1.25        # a new map must beat the current one's xp_per_step by 25% (untuned; named, not config)
MIN_DWELL_STEPS = 600     # no switch within this many planning steps of the last one (untuned)
MAX_TRAVEL_STEPS = 320    # same cap as Level_Banded: a map further than this is not a rung

def pick(spots: list, solo_ok, current: int | None, travel, since_switch: int) -> int | None:
    """The map to train on: among `spots` (atlas Spot rows already restricted to allowed AND known maps) the one with the
    best xp_per_step that `solo_ok(map_id)` is True for; if none is solo-ok, the best overall (today's behaviour).
    Stay on `current` unless a rung beats it by SWITCH_GAIN, travel(map) <= MAX_TRAVEL_STEPS and since_switch >= MIN_DWELL_STEPS.
    None when `spots` is empty (the caller then keeps the TRAIN_MAP pin: a missing table never sends the run somewhere new)."""
```

`train_target.stage_target(ctx)`: build `spots = atlas.rank_spots(..., candidates=allowed_and_known, top=len(allowed))` for the member being trained (`ctx.train_member` level, `need_level` = the stage's floor level from `team_floor.FLOOR_BY_GOAL`, growth from the species), keep only maps passing `training_ctl.target.known`-style reachability (a map never visited or with no learned route is not a rung: Viridian Forest and Route 2 are unvisited until the run first walks them, so the first version simply cannot pick them before they are known; report in 3.5 how often that happened), call `pick`, and fall back to `TRAIN_MAP[stage]` on None or any exception (log once). The pick is cached in `ctx.__dict__["ladder"] = {"map": ..., "since": step}` so it is sticky and one writer. Stages: `beat_brock` uses `stage_maps.PRE_BROCK`; `to_mt_moon` and `beat_misty` get a `LADDER_BY_STAGE` entry in `stage_maps.py` listing their sensible maps (Route 3 0x0E / Route 4 0x0F for Mt Moon; Route 24 0x23 and Route 25 0x24 for Misty), drawn from `encounters.MAP_NAMES`; `only_maps` and `stage_maps.allowed` keep their meaning for episodes (the new list is read ONLY by `stage_target`). Use the trainers: add `grind/trainer_spots.py`'s one-time trainers to the ranking only as a read in the report in this directive (making the picker walk to a trainer is a follow-up), because `trainer_spots` says so itself.

### 3.2 `training_ctl/release.py`: when a trainee stands alone

```python
PROBATION_FIGHTS = 3      # solo fights observed on this map before the observed record counts (untuned)
MIN_OBS_WIN = 0.9         # observed solo win share once PROBATION_FIGHTS exist
REVOKE_COOLDOWN = 400     # steps a revoked (slot, map) stays on the switch trick (untuned)

def verdict(ctx, slot, map_id) -> bool            # True = released
def note_battle(ctx, slot, map_id, *, won, hp_left, fainted, blackout) -> None   # the one writer
def released(ctx, slot) -> bool                    # roster.py re-exports this
```

Rules: released only when `solo_viable.is_solo_viable(party[slot], ROM_KB, ctx.view.m)` (missing data = NOT released, never a guess) AND the trainee is not a Magikarp AND not revoked. The model alone releases (probation: the Level_Banded 0.25 HP safety net stays in `trainee_out`); once `PROBATION_FIGHTS` solo fights exist on the map, the observed win share must also be at least `MIN_OBS_WIN`. Revoke for `REVOKE_COOLDOWN` steps on a faint, a blackout, or a fight won with `hp_left < solo_viable.SOLO_MARGIN * 0.5`; a revoked slot goes back to today's behaviour. State lives in `ctx.__dict__["release"]` keyed by (slot, map); bounded (keep the last 8 fights per key). Pure functions over that dict plus the party/kb the caller passes; no emulator reads inside `verdict` beyond what `roster.trainee_slot` already does.

`roster.released(ctx, slot)` delegates. `switch_out.trainee_out`: `return None` when `ep.get("solo")` (Level_Banded) OR `roster.released(ctx, t)`, with the same current-HP-at-least-`SWITCH_MIN_HP` condition. Nothing else in the switch menu code changes. While released, the lead is not escorted: the existing `want_home` exp rotation already puts the breaker at slot 0; verify it does, and if it does not, report instead of widening the change.

### 3.3 Floors and gate are untouched; assert it

A test must show that with the ladder and release active a party that does not meet `team_floor` is still held (`team_floor.ready` False, gym hold True) and that `stall_hold_holds` is unchanged. Do not edit `FLOOR_BY_GOAL`, `TEAM_FLOOR_MEMBERS`, `FLOOR_CAP_MULT`, `FLOOR_BLACKOUTS`, `STALL_HOLD_CAP`.

### 3.4 Tests (synthetic kb and ctx; no ROM, no emulator; build the kb like `tests/test_switch_matchup.py:11-34`)

`tests/test_area_ladder.py`: (1) the best xp_per_step wins and a tie keeps `current`; (2) a rung must beat `current` by `SWITCH_GAIN` and after `MIN_DWELL_STEPS` to switch (just under each stays); (3) a map beyond `MAX_TRAVEL_STEPS` is never picked; (4) empty spots returns None and `stage_target` falls back to the `TRAIN_MAP` pin; (5) unknown/unvisited maps are not rungs; (6) a solo-ok rung beats a higher-xp non-solo rung; none solo-ok returns the best overall; (7) `stage_target` on a stage without a ladder (Route 24 default) is unchanged; (8) the Forest (rate 8) loses to Route 1 (rate 25) on the real encounter numbers pasted in 1.1 (synthetic rows with those rates), proving the pick follows xp per step, not map order.
`tests/test_training_ctl_release.py`: (9) strong trainee on a weak map is released; weak trainee is not; missing data (empty moves, unknown species, no party row) is NOT released; Magikarp never; (10) probation: after `PROBATION_FIGHTS` fights with a win share under `MIN_OBS_WIN` the release drops; (11) a faint or blackout revokes for `REVOKE_COOLDOWN` steps then re-releases; (12) per-(slot, map) keys do not leak across maps; history stays bounded; (13) `trainee_out` returns None for a released slot at HP >= 0.25 and returns the slot under 0.25, when not released, and for a Magikarp; (14) floor held with release active (3.3); (15) a monotone model test: for synthetic Route 1 rows and a L8 trainee needing L12, expected fights-to-floor with release (full XP, no sharing, `xpmath.xp_gain` with participants=1) is below the switch-trick figure (participants=2), pinning the premise as arithmetic, not as a real-ROM claim.

### 3.5 Measure inside the run (report only, no behaviour)

Add one `ctx.log` line per ladder switch and per release/revoke (`[ladder] Route 1 -> Route 2 (xp/step 3.1 -> 4.0)`, `[release] slot 2 on Route 1: model 1.00 win, observed 4/4`). These lines are what the controller's real-ROM check reads. No new `decisions.jsonl` rows, no new run-dir files.

### 3.6 The shadow mismatch hypothesis (report only)

Write a test in `tests/test_training_ctl_shadow.py`'s style that builds a ctx with `ctx.view.battling = True` and a stale old flag (`floor_unmet` True, `train_member` 1) and shows `adapters.derived` returns `floor_unmet False, train_member None` (the party read is `[]` while battling). If it holds, say so in the Report as the likely source of the 70 mismatches; do NOT change `adapters.py`.

## 4. What NOT to do

- No ROM, no emulator process, no `runs/` access (absent in your worktree; do not look). Tests use synthetic kb / `SimpleNamespace` / `tmp_path`.
- Do not change a safety floor, the gym hold, `GrindBudget`, `area_grind`, `grind_episode._end_reason`, `stage_maps.PRE_BROCK`/`BY_STAGE`, `MIN_HP_FRACTION`, the episode caps, `readiness.py`, `team_plan.py`, `team_floor.py`.
- Do not edit `training_ctl/{adapters,controller,state,exit_rule,sustain,target}.py`, `party_order.py`, `bring_out.py`, the switch menu presses, the Magikarp switch-training plan (a Magikarp stays on switch-in).
- Do not add a config file, a CLI flag, a new goal, a ledger schema bump, or a new dependency. No file over 300 lines; `plan_goal.py` net 0.
- Do not claim real-ROM behaviour works: the real-ROM A/B is the controller's, not yours (below).

## 5. Verification (exact commands, from the worktree root)

Interpreter confirmed by Claude on 2026-11-15: `uv run python --version` prints `Python 3.12.12`. Baseline on origin/main 2346256 (before this work, before Level_Banded), real output:

```
uv run pytest -q -p no:cacheprovider tests/test_train_target.py tests/test_training_ctl_target.py tests/test_training_ctl_roster.py tests/test_training_ctl_exit.py tests/test_training_ctl_shadow.py tests/test_grind_points.py tests/test_grind_episode.py tests/test_area_grind.py tests/test_grind_pressure_plan_goal.py tests/test_switch_matchup.py tests/test_team_floor.py tests/test_explorer_behaviours.py
159 passed, 1 warning in 50.28s
```

After the work, the same command plus the new files must pass with 0 failed (Level_Banded's own tests add to the count):

```
uv run pytest -q -p no:cacheprovider tests/test_area_ladder.py tests/test_training_ctl_release.py tests/test_train_target.py tests/test_training_ctl_target.py tests/test_training_ctl_roster.py tests/test_training_ctl_exit.py tests/test_training_ctl_shadow.py tests/test_grind_points.py tests/test_grind_episode.py tests/test_area_grind.py tests/test_grind_pressure_plan_goal.py tests/test_switch_matchup.py tests/test_team_floor.py tests/test_explorer_behaviours.py
wc -l src/pokeagent/grind/area_ladder.py src/pokeagent/explorer/training_ctl/release.py src/pokeagent/explorer/train_target.py src/pokeagent/explorer/training_ctl/roster.py src/pokeagent/explorer/behaviours/switch_out.py src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/grind/stage_maps.py
git diff --stat origin/main
```

Expected: 0 failed, none skipped; each new module under 120 lines, `plan_goal.py` at or under 298, every file within its allowance in section 2; the stat lists only section 2 files, the two new tests and any adapted existing test. Full suite once at the end (pytest-xdist is not in this venv; do not use `-n`; about 3 minutes): `uv run pytest -q -p no:cacheprovider`, expected 0 failed.

**Not yours (the controller, on the laptop, after review): the real-ROM A/B, and it is a merge gate.** Devin cannot run it (no ROM in worktrees). Claude runs, from the deliver_parcel leg state saved by `--save-leg-states`, `tools/ab.py` with `--a-ref origin/main --b-ref <this branch>`, the flags in 1.1, goal `beat_brock`, cap 15,000 steps, seeds 1-3 for each of bulbasaur, charmander and squirtle (equal policy), one emulator at a time. Metrics from `evaluation_ab.extract_metrics` and `tools/step_budget.py`: steps to `beat_brock`, blackouts (summed), battles on the stage map, switch-trick battles vs solo battles, bench xp per 1k run steps, party levels at the gym door. PASS = median steps-to-Brock down at least 25% per starter with no starter worse, blackouts total not higher than A, party at the gym door still meets the floor (2 members >= L12) and `team_ready` unchanged, 0 failed tests, and the `[ladder]`/`[release]` log lines show a release that was not revoked on a faint. A synthetic-only result does not count (Robert, 2026-11-07: organic proof).

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the worktree. Do not search, glob or hunt for missing files: if something named here is missing, stop and write what in the Status row.
- Use `uv run` and Python 3.12 only; no bare `python`. Never `-n` (xdist is not installed).
- Create no scratch or debug files; if one is needed it goes under `.devin-scratch/` and stays.
- Work only on branch `directive/trainee-independence-area-ladder`; commit as you go; never commit to main/master, never push to main, never deploy, never merge. Do NOT hand-write a `## Queue` block or edit between the queue markers.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass. SOLID/SRP/KISS: small new modules, extend existing ones.
- If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `area_ladder.py` and `release.py` exist with the constants and functions in 3.1 and 3.2; missing data is never "released" and never a new map. <!-- test: tests/test_training_ctl_release.py::test_missing_data_is_not_released -->
- [ ] `stage_target` asks the ladder and falls back to the `TRAIN_MAP` pin; `plan_goal` line 239 uses it, net 0 lines. <!-- test: tests/test_area_ladder.py::test_empty_spots_falls_back_to_pin -->
- [ ] A released trainee is not switched out above 0.25 HP on the `train_route` path; a revoked or Magikarp trainee behaves as before. <!-- test: tests/test_training_ctl_release.py::test_trainee_out_stays_in_when_released -->
- [ ] Robert's expectation (2026-11-15): on a pre-Brock route (wild levels 2-5), a full-HP Rattata or Pidgey at level 5-6 is released to fight alone. Robert judged the Level_Banded first values (SOLO_MIN_WIN 0.95, SOLO_MARGIN 0.30) too strict because the per-battle nets (switch-out at SWITCH_MIN_HP, flee, heal, revoke on faint) catch the bad tail; Claude retunes them on the Level_Banded branch to SOLO_MIN_WIN 0.75 and SOLO_MARGIN 0.10 before it merges. Use the merged constants; a synthetic test pins level 5 and level 6 as released; report the sim win rate and HP for both. <!-- test: tests/test_training_ctl_release.py::test_level5_and_6_trainees_released_on_pre_brock_route -->
- [ ] The floor and gym-hold test (3.3) passes; no safety constant or file in section 4 changed. <!-- test: tests/test_training_ctl_release.py::test_floor_still_held_with_release_active -->
- [ ] Section 5 commands: 0 failed, line counts within allowance, diff stat limited to section 2.
- [ ] Committed on the branch; Status row set to `Review` with the evidence.

## 8. Report

Findings first: how `pick` and `release.verdict` landed (final constants), how often a first-version ladder had no known alternative rung and fell back to Route 1 in the synthetic cases (3.1), whether `want_home` already puts the released trainee at slot 0 (3.2), and the shadow-mismatch hypothesis result (3.6). Then the real output tails of the baseline and after commands, the `wc -l` table and the diff stat. Then anything unsettled. Do not claim real-ROM behaviour works.

## Required from User

Nothing for the build. Queue only after `Level_Banded_Grind_Directive.md` has merged (Party_View is already merged, #210). The real-ROM A/B in section 5 is run by Claude before merge.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.
- Never publish a ROM or save state anywhere (hard rule, 2026-11-08).

## Sandbox needs

- Read(docs/directives/Level_Banded_Grind_Directive.md)
- Read(src/pokeagent/explorer/train_target.py)
- Read(src/pokeagent/explorer/behaviours/plan_goal.py)
- Read(src/pokeagent/explorer/behaviours/switch_out.py)
- Read(src/pokeagent/explorer/behaviours/battle.py)
- Read(src/pokeagent/explorer/training_ctl/roster.py)
- Read(src/pokeagent/grind/atlas.py)
- Read(src/pokeagent/grind/stage_maps.py)
- Read(src/pokeagent/grind/solo_viable.py)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git ls-files)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-trainee-independence-area-ladder--9f407a |
| Base branch | - |
| Base commit | 1381767f53b5bdbf6c704e9ed375bef383a29fa2 |

**Status log**
- 2026-11-15 18:54 · robert-claude-laptop · none → Queued
- 2026-11-15 18:55 · robert-claude-laptop · Queued → Approved — lint override: The three cited paths (grind/area_ladder.py, training_ctl/release.py, tests/test_area_ladder.py) are new files this directive creates; absent at main by design.
- 2026-11-15 19:22 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-trainee-independence-area-ladder--9f407a; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7GVR1KBH7MY4AT7FTH3F8NS
<!-- queue:end -->
