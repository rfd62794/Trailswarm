# PokeAgent: grind points - a shared ledger of known-good level-grind spots, chosen by the team's level gap, measured in real xp/min, and reused by every run

## Why this exists

Robert, 2026-11-07, watching the 60k-step marathon: "Prior agents were also getting stuck during grind attempts on the
map transition toward Nugget Bridge and never were able to progress without my guidance. Can we build a collection
of known good level grind points and reuse and exploit them?" and "as the team grows, exploit the available
options; grinding becomes more important."

Measured facts (inventory 2026-11-07, main a27b4ef):

- A grind ATLAS exists but nothing chooses from it. `src/pokeagent/grind/atlas.py` (80 lines): `Spot` dataclass
  (map_id, name, xp_per_battle, encounter_p, n_obs, win, blackout, hp_lost, battle_steps, travel_steps, xp_per_step,
  xp_per_min, steps_to_goal, note); `rank_spots` scores `xp_b / (1/p + bsteps + travel + blk*BLACKOUT_STEPS)`;
  priors PRIOR_WIN 0.92, PRIOR_BLACKOUT 0.02; `STEPS_PER_MIN = 3600/FRAMES_PER_STEP` with `FRAMES_PER_STEP = 16`
  marked ASSUMPTION (atlas.py:10). `grind/refresh.py` folds `runs/battles.jsonl` into `runs/grind_atlas.json` every 5
  finished swarm runs. Only `item_policies/policy.py:59` and `rare_candy.atlas_minutes` read the atlas.
- Many ranked spots are prior-only: in `runs/grind_atlas.json` (65 KB, 282 stat keys), e.g. BULBASAUR beat_misty L12:
  ROUTE_24 (map 35) 268.5 xp/min with n_obs 0, ROUTE_25 (36) 255.6 with n_obs 0. `inputs.need` = BULBASAUR {brock 13,
  misty 23, surge 36}, CHARMANDER {17, 25, 36}, SQUIRTLE {10, 25, 46}; `inputs.center_cost["35"]` = 416 frames,
  `["3"]` = 128.
- `explorer/behaviours/grind_drill.py` (40 lines) only applies when `ctx.opts.drill_grind == view.m`, i.e. a human
  passed `--drill-grind MAP` to tools/explore_demo.py. `grind/drill.py` GrindDrillMonitor writes
  `runs/legs/grind_drills.jsonl` (GRIND_LOG), which has NEVER been written on this machine (file absent). No measured
  xp/min exists; `runs/xp_estimates.jsonl` (15,246 rows) is estimates only (`estimated: true` on every row, method
  "gen1: base_exp*level/7, x1.5 trainer, one participant"); `runs/battles.jsonl` (17,073 rows) has no exp_gained.
- The training gate and need levels exist: `explorer/training.py` TRAIN_LEVEL_BY_GOAL (:17-22), `required_level`
  (:102-116, clamps the readiness verdict to table + CAP_ABOVE_TABLE 5); `explorer/grind.py` GrindBudget
  (GRIND_BATTLES 25, GRIND_STEPS 2500, GRIND_BLACKOUTS 2, CEILING_MARGIN 6) lifts the gate after a budget;
  `explorer/train_route.py` (39 lines) hard-codes "walk toward Route 24 grass" (CERULEAN = 0x03, encounters from
  `mem.data["maps"]["35"]`); `explorer/area_grind.py` AREA_GRIND_STEPS 400 / AREA_GRIND_BATTLES 6.
- The Nugget Bridge stall is a map-boundary ping-pong, not a grind rule: across runs since 2026-11-05 there are 1,930
  map 3<->35 crossings at (3,21,0)<->(35,11,35) and (3,20,0)<->(35,10,35); 152 runs have >= 4. In the marathon run
  (explore-20261107-191457-26240) 358 crossings between steps 17,233 and 42,768: `plan_goal` (goal beat_misty) walks
  UP into Route 24 and `frontier` on map 35 walks DOWN back into Cerulean (decision rules at crossings: frontier 167,
  plan_goal 179). Review tool lines: "@18375 map_bounce 3<->35 x72 (865 presses)". Other runs: 035142-18964 "@284
  map_bounce 35<->3 x44 (623 presses)", 154607-17376 "@295 map_bounce 3<->35 x2 (984 presses)". No grind/drill/train
  rule was deciding at the crossings. Human presses broke 5 of the 358 crossings.
- Trainer grind ranking landed in PR #158 (`src/pokeagent/grind/trainer_spots.py`, report-only; `tools/grind_report.py`).
- Registry order (`explorer/behaviours/__init__.py:44-58`): ... Goto, ReplayBeat, StallGuard, Heal, Restock,
  StatusCare, UseItems, GoalTalk, GrindDrill, ExploreBurst, Pickup, PlanGoal, LearnerHunt, TeamHunt, Frontier.
- Sizes: grind/ total 409 lines across 7 files; grind_drill.py 40; plan_goal.py 168; training.py 126;
  `explorer/context.py` 296 and `explorer/memory.py` 298 against a 300-line ceiling enforced by
  `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size` for everything under `explorer/`.

Read first: the files named above; `docs/directives/Segment_Scorecard_Directive.md` (segments and the curriculum
this must not break); `docs/KNOWLEDGE.md` "Game knowledge drain". Then `uv run pokeagent review run
runs/explore-20261107-191457-26240` if the run directory is present (it is gitignored; absent in a worktree, in
which case skip it and rely on the numbers above).

## Scope (in this order)

1. `src/pokeagent/grind/points.py` (new, pure): the grind-point ledger and its selection function.
2. `src/pokeagent/grind/measure.py` (new, pure): measured xp/min from run records, and FRAMES_PER_STEP calibration.
3. Wire `GrindDrill` to the ledger: it applies by itself when the training gate says "under level", not only
   under `--drill-grind`.
4. Boundary guard: a grind episode pins the agent to the grind point's map set, so plan_goal/frontier cannot
   ping-pong across the Cerulean/Route 24 edge during a grind.
5. `tools/grind_report.py`: print the ledger (measured vs prior) and the chosen point per (starter, next boss).
6. Tests for all of it; a `docs/KNOWLEDGE.md` paragraph.

## The work

### 1. `grind/points.py` (under 300 lines)

- `GrindPoint` dataclass: `map_id`, `name`, `patch` (list of `(x, y)` grass tiles, from `mem.data["maps"][str(map)]
  ["encounters"]` keys "x,y" with count >= 1), `species` (list of (internal id, min level, max level) from
  `wild_by_map` in the ROM kb when present, else from observed battles), `level_band` (lo, hi: the party levels this
  point is good for; default `max species level - 2 .. max species level + 6`), `xp_per_min_measured` (float | None),
  `xp_per_min_prior` (float from the atlas `rank_spots`), `n_measured` (episodes), `center_map`, `center_cost_frames`
  (from `grind/centers.py` `center_costs`), `blackout_rate` (measured over episodes, else PRIOR_BLACKOUT),
  `provenance` ("organic" | "synthetic" | "mixed", per the repo's synthetic-proof rule), `updated` (ISO time).
- `GrindLedger`: load/save `runs/grind_points.json` (atomic write via a temp file + `os.replace`; schema version 1;
  tolerate a missing or malformed file by starting empty and logging once); `upsert(point)`; `merge(other)` for
  swarm memory merge (union by `map_id`; measured values combine by episode-weighted mean; organic never overwritten
  by synthetic; idempotent); `seed_from_atlas(atlas_json)` to create prior-only points from `runs/grind_atlas.json`.
- `choose(ledger, party_levels, need_level, current_map, mem) -> GrindPoint | None`: deterministic. Candidates whose
  `level_band` contains the trainee's level (the lowest party member that is being trained, or the lead when there
  is no trainee) and whose `xp_per_min` (measured if `n_measured >= 2`, else prior) is highest after subtracting a
  travel cost `travel_steps(current_map -> map_id) / STEPS_PER_MIN` and a blackout penalty `blackout_rate *
  BLACKOUT_STEPS`. Ties by `map_id`. Return None when the gap `need_level - trainee_level <= 0`.
- `episode_result(point, xp_gained, steps, blackouts) -> GrindPoint`: fold one grind episode in (measured xp/min
  = xp_gained / (steps / STEPS_PER_MIN); running mean by episode count).
- Shared memory: `tools/swarm_merge.py` gains `merge_grind_points(dst, src)` under `mem.data["grind_points"]`, called
  from `merge_memory` like `merge_trainers` is. The ledger file is the run-local copy; the shared table is the merged
  one; on run start the run seeds from the shared table if the file is missing.

### 2. `grind/measure.py` (under 200 lines)

- `frames_per_step(transitions_rows) -> float | None`: the median of frame deltas between consecutive agent-sourced
  transition rows that `moved` (rows carry `step` and the run's `levels.jsonl` carries `frame`; use whichever the
  transitions have; if transitions carry no frame field, compute from `levels.jsonl` (frame, step) pairs instead).
  Replace the `FRAMES_PER_STEP = 16` ASSUMPTION in `atlas.py` with `measure.frames_per_step_or_default(runs_dir)`
  that uses the median over the last 20 runs and falls back to 16 with a one-time log line. Keep `STEPS_PER_MIN`
  as a function of it.
- `xp_gained_in_episode(levels_rows, start_step, end_step) -> int`: the party exp total delta from `levels.jsonl`
  rows (`party` entries are `[species, level, exp, hp, max_hp]`) between the two steps. This is MEASURED xp (the
  exp field is read from RAM), unlike `xp_estimates.jsonl`.
- `GrindDrillMonitor` (grind/drill.py) must log every grind episode, not only `--drill-grind` runs: write one row
  per episode to `runs/legs/grind_drills.jsonl` with run, map, start/end step, xp_gained (measured), steps,
  blackouts, xp_per_min, provenance.

### 3. `GrindDrill` applies by itself

- `explorer/behaviours/grind_drill.py`: `applies()` becomes `ctx.opts.drill_grind == view.m` OR (`ctx.grind_episode`
  is active for `view.m`). A grind episode is started by a small new `explorer/grind_episode.py` (under 150 lines)
  called from `GrindDrill.applies` through a cheap check: when the training gate says under level (reuse
  `training.required_level` / `gate_for` and the GrindBudget in `explorer/grind.py`; do NOT duplicate the gate),
  no episode is active, not in battle, and `points.choose(...)` returns a point: start an episode `{point, start_step,
  start_xp, blackouts, route}` stored in the existing `ctx._grind_state` dict (grind_drill.py already keeps it there;
  do not add fields to `explorer/context.py`, which is at 296 lines).
- Routing to the point: reuse the existing walk machinery (`memory_nav`/`WorldGraph` BFS as `heal_walk.py` from
  PR #159 does, or `train_route.step` generalised to take a map id and a patch instead of hard-coded Route 24).
  Replace `train_route.py`'s hard-coded Route 24 with the chosen point; keep its public names working.
- Episode end: when the trainee reaches `need_level`, when `AREA_GRIND_STEPS`-style caps hit (reuse the GrindBudget
  constants), after 2 blackouts, or when HP < MIN_HP_FRACTION with no potion (then the heal path takes over). On end,
  `episode_result` is folded into the ledger and the drill row logged. Log one line at start and end.

### 4. Boundary guard

- While an episode is active, `train_route.stay_on_route` (already returns `{CERULEAN}` while training on Route 24)
  must return the point's `map_id` plus its Pokecenter map, and BOTH `plan_goal` and `frontier` must honour it:
  check how `stay_on_route` is consumed today (grep), and make `frontier` skip targets outside the set while an
  episode is active (one check in `_frontier_move`'s candidate filter; frontier.py is 137 lines after PR #164). This
  is the Nugget Bridge fix: during a grind, no behaviour may step onto a warp or edge tile that leaves the set.
- Regression test (synthetic, labelled): a fixture map 35 with the edge tiles (35,10,35)/(35,11,35) warping to map 3,
  an active episode on 35, frontier's only "unexplored" candidates across the edge: the chosen press never leaves
  map 35; without an episode it may.

### 5. `tools/grind_report.py`

- Add a `--points` mode: print the ledger as a table (map, name, band, xp/min measured (n) vs prior, center cost,
  blackout %, provenance) and the `choose(...)` result for each (starter, next boss, trainee level) in
  `inputs.need`. Keep the existing report intact. The 225 steps/min literal becomes the measured value with
  "(measured over N runs)" or "(assumed 16 frames/step)".

### 6. Tests and docs

- `tests/test_grind_points.py`: ledger load/save/merge idempotence; organic-not-overwritten-by-synthetic; `choose`
  determinism and band filtering; travel/blackout penalties change the pick in the expected direction;
  `episode_result` running mean.
- `tests/test_grind_measure.py`: `frames_per_step` on a synthetic transitions/levels fixture; `xp_gained_in_episode`.
- `tests/test_grind_episode.py`: start/end conditions, budget reuse, the drill row written, the boundary guard above.
- `tests/test_explorer_behaviours.py` must stay green (order test may need `GrindDrill` unchanged in place).
- `docs/KNOWLEDGE.md`: a short "Grind points" paragraph: the file, the schema, measured vs prior, how to read the
  report, and the Nugget Bridge boundary rule.

## What NOT to do

- Do not edit `planner*.py`, `ship_gate.py`, `team_value.py`, the curriculum/segment store, `seg_sched.py`.
- Do not change the atlas scoring formula or priors; the ledger wraps the atlas, it does not replace it.
- Do not add fields to `explorer/context.py` or `explorer/memory.py` (both are at the 300-line ceiling).
- Do not hard-code map ids for grind spots except in tests; the ledger is data.
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree; if a file this
  directive names is missing, stop and say so in the Status row.
- Do not pretend measured data exists: `runs/` is gitignored and absent in a worktree, so every measured path is
  covered by synthetic fixtures (labelled synthetic). The controller validates against real runs afterwards.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_grind_points.py tests/test_grind_measure.py tests/test_grind_episode.py tests/test_explorer_behaviours.py tests/test_train_route.py tests/test_grind*.py
```
Expected: all pass (adjust the list to the files that exist; `ls tests/test_grind* tests/test_train*`).

```
uv run pytest -q
```
Expected tail at main 41208f8 or later: ~1866+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/grind/*.py src/pokeagent/explorer/grind_episode.py src/pokeagent/explorer/behaviours/grind_drill.py src/pokeagent/explorer/behaviours/frontier.py src/pokeagent/explorer/train_route.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
```
Expected: every file under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run; never install, download, fetch, or read outside
  the working directory.
- Work only on the branch named in your run header; commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- `runs/grind_points.json` schema + ledger + `choose` exist and are tested; GrindDrill starts episodes by itself when
  under level; grind episodes are logged with MEASURED xp; the boundary guard test passes; the report prints the
  ledger; KNOWLEDGE.md updated; all suites green; sizes under 300.
- Status row set to Review with diff stat, the wc -l line, and the test tails.

## Report

Diff stat, the three test tails, the wc -l line, which constants you chose differently and why, and the list of
things the controller must validate on real runs (measured xp/min for Route 24 vs Route 25 vs Mt Moon, the calibrated
frames/step, and a headless grind episode from `baselines/` that ends without a 3<->35 bounce).

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-grind-points-directive |
| Base branch | - |
| Base commit | 37fe0cdc4abbc77cad7acc78d4500ded33cb7d35 |

**Status log**
- 2026-11-07 20:30 · robert-claude-laptop · none → Queued — Claude 2026-11-07 from Robert's request (known-good grind points, reuse and exploit them; Nugget Bridge transition stall); inventory-backed
- 2026-11-07 20:31 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives (greenfield modules); Robert asked for this tonight
- 2026-11-07 20:31 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-grind-points-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6WCG3R86P640TYE1DK3RETD
<!-- queue:end -->
