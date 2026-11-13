# Training Controller: one owner for "who trains, where, and when to heal" (2026-11-13, rev 2)

Status: design draft, no code. Evidence: seed 12, heal_cerulean -> beat_misty, 12000 steps,
`rev-c3/runs/explore-20261113-045255-6868/console.log` (counts = decision lines; one line = one step). All paths are
under `src/pokeagent/` unless shown. Limits: explorer files <= 300 lines (`explorer/context.py`, `explorer/memory.py`,
`explorer/behaviours/plan_goal.py` at 300; `explorer/battle.py` is 230); new modules < ~120 lines with own tests.

## 1. Problem: three (really five) systems steer training

| Decision | Owner(s) today | Conflict in the log |
|---|---|---|
| Where | `explorer/train_route.py` via `behaviours/plan_goal.py:130-133`; `explorer/grind_episode.py` + `grind/points.py` choose; `explorer/train_target.py`; frontier avoid_maps (`behaviours/frontier.py:155`) | 13 episode starts: 10 VIRIDIAN_FOREST, 1 MT_MOON_B1F, 2 ROUTE_24. Agent was never on 0x33/0x3C, so 11 episodes were phantom pins: 5,551 steps (46%); 11 of 13 ended "hurt with no potion"/"party membership changed". "walking to grass" 1,587 (13.2%), 1,092 in Cerulean |
| Who | `explorer/behaviours/party_order.py`; `behaviours/switch_out.py`; `explorer/training.py` gate_state -> `ctx.train_member`; `explorer/trainee_gate.py`; `magikarp.trainee_slot_for` | 42 reorder sessions (503 lines, 4.2%): 25 Route 24, 14 in the Cerulean Pokecenter right after heals, 3 Cerulean. 167 of 862 SHAKEs within 40 steps of a reorder press. switch_train 163 |
| Heal | planner rule (`explorer/planner.py:22,41,142`, inputs `_hp/_survives/_push_on` built in plan_goal), `explorer/grind_heal.py`, `behaviours/retreat_heal.py`, `explorer/after_heal.py`, restock | 34 trips: 897 steps to the Pokecenter (7.5%) + 64 nurse; 537 start on Route 24, 345 Cerulean. retreat_heal logged 0 lines, heal_walk 1 start: trips are the planner's rule. Mart walks 102 lines |
| Leave PC | planner "leaving the Pokecenter" vs frontier | 652 steps (5.4%), 34 visits; 647 frontier "patrolling" lines all in 0x40 vs 641 plan_goal "leaving" lines: owners alternate |
| Gym hold/floor | plan_goal (`gym_hold_seen` :82,:149), `explorer/training.py:125` floor_unmet; readers `behaviours/goal_talk.py:60`, `behaviours/frontier.py:150`, `explorer/grind.py` stall_hold_holds | beat_misty never reached; party L8-10 x5 + L25, floor L19 for 2 |
| Loop guard | `explorer/center_visit.py`, LoopGuard | 862 SHAKE (7.2%): Cerulean 483, Pokecenter 210, Route 24 168. **Out of scope, unchanged; measured only** |

Root cause: target, roster and "hurt" are re-derived from ctx flags with several writers and different timing. Real second
writers: `explorer/behaviours/grind_loop.py:32` mark_live (`train_route_live`); `explorer/grind_episode.py` tick called at
`explorer/engine.py:52` (`_grind_state`); `explorer/training.py:125` (`floor_unmet`); `train_member`/`train_need` from the locals at
`behaviours/plan_goal.py:60-107`.

## 2. Design

`TrainingState` (frozen dataclasses) at `ctx.__dict__["training"]`; pure sub-system functions; one facade in
`explorer/training_ctl/`: `state.py` ~50, `target.py` ~90, `roster.py` ~100, `sustain.py` ~90, `exit_rule.py` ~60,
`controller.py` ~110, `adapters.py` (thin ctx readers) .

```python
class TrainingController:
    def observe(self, ctx) -> None            # slice 1: shadow only; called from explorer/engine.py right after selector.choose (plan_goal has run); asserts == old flags
    def tick(self, ctx) -> None               # slice 3+: sole writer, once per step
    def training(self) -> bool;  def target(self) -> Target | None   # (map_id, patch, center_map), stable per session
    def roster(self) -> Roster | None         # lead_slot, trainees (<=2), order_wanted only at session boundary
    def heal_now(self) -> Sustain             # .go, .use_potion, .why
    def allowed_maps(self) -> frozenset | None;  def step_toward(self, ctx) -> tuple | None
```
- **Target**: one point per session via `grind/points.py` choose (kept as scorer); rejects points with no learned path.
- **Roster**: ONE trainee-selection owner. `trainee_gate` keeps only the eligibility check (pure), `switch_out` only executes
  battle swaps from `roster.trainees`, `magikarp.trainee_slot_for` becomes `roster` lookup (6 call sites migrate). Order change only at a
  session boundary; `party_order` stays the menu walker.
- **Sustain**: owns the heal rule. The planner stops owning it in slice 3: `explorer/planner.py` heal branches (:41 etc.) read
  `heal_now()` instead of `_hp/_survives/_push_on`; Potion `outside_use.field_wants` then walk.
- **Exit**: owns `GrindBudget`/`ctx.grind` (`explorer/grind.py`) and the stall-hold/`gate_lifted`/`lifted_need` state (slice 5).

## 3. Reader/writer migration

| Item | Today's owner | Slice | After |
|---|---|---|---|
| `behaviours/grind_loop.py` (mark_live, paced_in_training) | writes `train_route_live` | 3 | Target (`training()` query) |
| `behaviours/grind_drill.py:44` | reads episode/under-level | 2 | Target+Exit query |
| `behaviours/learner_hunt.py`, `team_hunt.py`, `trainer_hunt` (`hunt_grass`) | own flag writers | 5 | read `training()`; out of scope until then |
| `explorer/grind.py:29` grinding_now | episode or map | 5 | Exit |
| `explorer/party_log.py:183` | reads `train_need` | 3 | Exit (`need`) |
| `explorer/par_follow.py:113` | reads `train_need`/`gate_lvl` | 3 | Exit |
| `explorer/trainee_gate.py` + `magikarp.trainee_slot_for` (6 sites) | trainee pick | 4 | Roster |
| `explorer/area_grind.py` | steps/battles caps | 5 | Exit |
| planner heal rule (`explorer/planner.py`) | planner | 3 | Sustain |
| `GrindBudget`/`ctx.grind`, team_plan st `gate_lifted`/`lifted_need` | plan_goal :139-142 | 5 | Exit |
| `explorer/after_heal.py`, `grind_heal.py` | adapters | 3 | folded into Sustain |
| `behaviours/goal_talk.py:60`, `behaviours/frontier.py:150` (gym_hold_seen / floor_unmet readers) | read flags | 5 | `training()` + Exit queries |
| `explorer/planner_east.py:114` (reads `_survives`/heal keys) | planner | 3 | Sustain (moves with the planner heal rule) |
| trainee_slot_for sites: `behaviours/catch.py:47`, `behaviours/switch_out.py:37`/`:88`, `explorer/grind_episode.py:92`, `explorer/trainee_gate.py:41`/`:66` (def `magikarp.py:37`) | trainee pick | 4 | `roster()` |
| `gate_lifted`/`lifted_need` writers `behaviours/plan_goal.py:283`/`:297`/`:298` (readers :139-151) | plan_goal | 5 | Exit |

## 4. Slices (each mergeable, A/B on seed 12; gating tests)

1. **Shadow controller (zero behaviour change).** `observe` runs after plan_goal's computation, derives target/roster/
   sustain/exit through existing functions, and asserts equality with `train_route_live`, `_grind_state`, `gym_hold_seen`,
   `floor_unmet`, `train_member`, `train_need` in tests/log only. No ordering change, no writer moved; decisions.jsonl must be
   byte-identical. Extend `tools/step_budget.py` (below). Net lines in plan_goal/context: 0. Gate: `tests/test_train_route.py`,
   `test_train_target.py`, `test_grind_episode.py`, `test_plan_goal_gym_road.py`.
2. **Target.** Breaks the `train_target` <-> `grind_episode` import cycle (episode start calls Target; Target no longer imports
   grind_episode). Removes the `train_target` import (`behaviours/plan_goal.py:16`, shared line, 0 net) and the `route_kw` kwarg at :133 (about -1). context.py: 0. The cycle is already half-broken by the lazy import at `explorer/grind_episode.py:106`; slice 2 deletes that workaround once Target owns the point choice. Gate: `test_grind_points.py`,
   `test_grind_episode.py`, `test_train_target.py`, `test_training_v2_slice3.py`.
3. **Sustain (after Target).** First writer move: `tick` becomes sole writer of `train_route_live`. Removes `after_heal` import (:16, 0 net),
   the :131-133 branch (about -3), the heal inputs in the plan_step dict (`behaviours/plan_goal.py:125`, about -1 to -2), and `grind_heal` calls in `behaviours/retreat_heal.py` and
   `behaviours/frontier.py:149`; `planner_east.py:114` and the `planner.py` heal branches read `heal_now()`. plan_goal est. -5, context 0. `explorer/context.py:124` stays until grind_loop's writer is gone. Gate: `test_retreat_heal.py`, `test_frontier_patrol.py`, `test_early_training_gate.py`.
4. **Roster.** `team_sig` (species, level, fainted: `party_order.py:31-34`) keeps species and level but replaces the fainted bit with a
   monotonic faint counter (alive->fainted increments, fainted->alive never does). Regression tests: a level-up reorders; a real faint
   (counter +1) reorders; a heal-revive (fainted->alive) does NOT; no 300-step expiry returns (incident `party_order.py:37-42`: 31 reorders). plan_goal/context est. 0. Gate: `test_party_order_ascending.py`,
   `test_party_log_reorder.py`, `test_trainee_gate.py`, `test_trainer_grind.py`.
5. **Exit + gym hold.** Fold `_end_reason`, stall hold, GrindBudget; delete `gym_hold_seen` (`behaviours/plan_goal.py:82`, :149) and the gate_lifted block (:139-151, :283, :297-298; est. -20), `floor_unmet` (`training.py:125`), then `explorer/context.py` fields :124, :165, :187 (-3) once their last writer is gone, and dead modules. Gate: `test_grind.py`, `test_area_grind.py`, `test_grind_pressure_plan_goal.py`, `test_plan_goal_gym_road.py`.
Estimated net removal: plan_goal about -26 total, context -3. Each slice's removals must make plan_goal/context line count net <= 0 (check `wc -l` in review).

## 5. Acceptance (tools named)

Runs are deterministic (identical 12000-step runs seen), so one seed-12 A/B per slice is valid; add seed 13 as a sanity check from slice 2.
Baseline: Route 24 210 xp/1k, SHAKE 7.2%, heal 7.5% + leave-PC 5.4% = 12.9%, 42 reorder sessions, 13 episode starts.
Slice 1 extends `tools/step_budget.py` with rows: reorder_party (sessions), grind-episode starts by map, blackouts.
- Route 24 xp/1k >= 210: new `tools/step_budget.py` row reading `xp_rates.jsonl` map_summary (no existing tool reads it). SHAKE <= 7.2%, heal + leave-PC < 12.9%: `tools/step_budget.py`.
- Reorder session = a maximal run of reorder_party decision lines with gaps <= 3 steps; target: 0 inside a Pokecenter, <= 5 total.
- Episode starts on never-visited maps = 0 (step_budget start-by-map row). Floor progress (2 members reach L19 no later; blackouts not up): a `step_budget.py` row reading `levels.jsonl` (step each member first reaches its level; no reader exists, slice 1 adds it).
- beat_misty is not reached today in 12000 steps, so "no regression" means floor progress above, not a time.
- EVERY slice: the full test suite passes with 0 failed (hard rule, no "known failures"), run before merge.
- Unit tests per sub-system: target, roster, sustain, exit_rule, controller (shadow equals old flags), plus ported tests above.

## 6. Risks / what NOT to do
- No lines added to `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`. Do not move writers in slice 1.
- Moving the writer to run before behaviours (slice 3) changes flag timing: test readers never see last-step values.
- Do not delete `grind/points.py` or the ledger. Loop guard stays untouched. No ROM run beyond the approved A/B gate; Mart/restock out of scope.
