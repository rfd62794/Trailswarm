# Training Controller: one owner for "who trains, where, and when to heal" (2026-11-13)

Status: design draft for review. No code changes. Evidence: seed 12, heal_cerulean -> beat_misty, 12000 steps,
`rev-c3/runs/explore-20261113-045255-6868/console.log` (counts are decision lines; one line = one step).
Hard limits: explorer files cap at 300 lines (context.py, memory.py, plan_goal.py at 300, battle.py at 299: add no lines
there, only delete); new modules < ~120 lines with their own tests; SOLID / SRP / KISS.

## 1. Problem: three (really five) systems steer training

| Decision | Owner(s) today | Conflict seen in the log |
|---|---|---|
| Where to train | `train_route.step` via plan_goal:133 (team_ready); `grind_episode` + `grind.points.choose` (episode point/patch); `train_target.only_maps/route_kw` glue; `frontier` avoid_maps via `train_route.stay_on_route` | 13 episode starts: 10 VIRIDIAN_FOREST, 1 MT_MOON_B1F, 2 ROUTE_24. The agent never stood on 0x33 or 0x3C (0 steps), so 11 episodes pinned frontier to a map it never visited: 5,551 steps (46%) under a phantom pin; 11 of 13 ended "hurt with no potion" / "party membership changed". "walking to grass" 1,587 steps (13.2%), 1,092 of them crossing Cerulean |
| Who trains | `party_order` (lowest level first, `team_plan.next_swap`); `switch_out` / `switch_train`; `training.gate_state` -> `ctx.train_member`; `trainee_slot_for` (5 callers) | 42 reorder sessions, 503 reorder_party lines (4.2%): 25 on Route 24, 14 inside the Cerulean Pokecenter right after a heal (the revive flips the `team_sig` fainted bit), 3 in Cerulean. 167 of 862 SHAKEs (19%) fall within 40 steps of a reorder press. `switch_train: MAGIKARP out, CHARMELEON in` 163 lines |
| Heal now | planner heal rule (`_hp/_survives/_push_on` into `plan_step`), `grind_heal.needs_heal` (frontier `weak`, retreat_heal gate), `retreat_heal`, `after_heal`, `center_visit`, restock "to a Mart" | 34 heal trips: 897 steps to the Pokecenter (7.5%) + 64 nurse steps; 537 started on Route 24, 345 in Cerulean. retreat_heal logged 0 lines and heal_walk 1 start, so the trips are the planner's own rule: the survival floor has at least three readers. Restock walks ("N steps to a Mart", 102 lines) cross the same Route 24 <-> Cerulean road |
| Leave the Pokecenter | planner "leaving the Pokecenter" (`after_heal.leaving` hands off to `train_route.step` only while training_live and the party survives) vs `frontier` | 652 steps (5.4%) over 34 visits; 647 frontier "no frontier: patrolling" lines, all in 0x40, interleaved with 641 plan_goal "leaving (2 steps)" lines: two owners alternate around (3-4, 6-7) |
| Gym hold / floor | plan_goal hold logic (`gym_hold_seen` set at :82 and :149), `training.gate_state` (`floor_unmet`); readers `goal_talk:60`, `frontier:150`, `grind.stall_hold_holds` | Stage never completes: party L8-10 x5 + L25 at step 12000, Misty floor L19 for 2 members; beat_misty not reached |
| Loop guard | `center_visit.exempt`, `LoopGuard` | 862 SHAKE lines (7.2%): Cerulean 483 (top tiles (20,3), (20,4), (20,5) on the road to Route 24), Pokecenter 210, Route 24 168 |

Root cause: each system re-derives target, roster and "hurt" from ctx flags (`train_route_live`, `_grind_state["episode"]`,
`gym_hold_seen`, `floor_unmet`, `train_need`, `train_member`) written at different points in the step, so readers see
one-beat-stale or contradictory answers. Nothing owns a session.

## 2. Design

One dataclass `TrainingState` on `ctx.__dict__["training"]` (context.py untouched) and one facade. Sub-systems are pure
functions over small frozen dataclasses; only the facade touches ctx. Package `src/pokeagent/explorer/training_ctl/`.

```
training_ctl/
  state.py       TrainingState, Session (session_id, target, roster, started_step, reason)                 ~50
  target.py      choose_target(maps, ledger, party, stage_maps, current) -> Target(map_id, patch, center)  ~90
  roster.py      plan_roster(party, floor, prev) -> Roster(lead_slot, trainees, order_wanted)              ~100
  sustain.py     heal_decision(party_view, target, potions, center_steps) -> Sustain                       ~90
  exit_rule.py   exit_reason(session, party, floor, budget, blackouts) -> str | None                       ~60
  controller.py  TrainingController.tick(ctx) + the queries below                                          ~110
  adapters.py    thin ctx readers (party view, potion count, floor verdict, maps) so the rest stays pure
```

Facade (the only thing other behaviours import):

```python
class TrainingController:
    def tick(self, ctx) -> None                 # once per step, engine hook BEFORE behaviours; sole writer of state
    def training(self) -> bool                  # am I in a training session?
    def target(self) -> Target | None           # (map_id, patch, center_map), stable for the whole session
    def roster(self) -> Roster | None           # lead + trainees; an order change is wanted only at a session boundary
    def heal_now(self) -> Sustain               # .go: bool, .use_potion: bool, .why: str
    def allowed_maps(self) -> frozenset | None  # replaces OutsideSet / avoid_maps glue
    def step_toward(self, ctx) -> tuple | None  # the one grass-walk press (absorbs train_route.step)
```

Sub-systems, one responsibility each:
- **Target**: pick once at session start from the ledger (`grind.points.choose` stays as the scoring function) plus
  `stage_maps`; never re-chosen mid-session; a point the agent has no learned path to is rejected (kills the 0x33
  phantom). Route 24 stays the team_ready target. Replaces `train_target.*` and the start half of `grind_episode`.
- **Roster**: the lowest-level member under the floor leads; trains at most two members toward `floor.level`; emits an
  order only at session start/end (never inside a Pokecenter, never on a fainted-flag flip): `team_sig` drops the fainted
  bit and the check is "lead is still the lowest trainee". Absorbs `party_order.want_home/_held`; `party_order` stays as the
  menu walker (113 lines, unchanged). `switch_out/switch_train` read `roster.trainees`.
- **Sustain**: one answer to "heal now": survival floor (`retreat_risk.party_survives`) first; a Potion
  (`outside_use.field_wants`) when cheaper than the walk; else walk. Also sets a leave-center hint so planner and frontier
  stop alternating. Replaces `grind_heal`, the planner `_hp/_survives/_push_on` inputs and retreat_heal's gates
  (retreat_heal becomes a thin adapter).
- **Exit**: floor met for N members, budget (`GrindBudget`), blackouts, or session timeout; returns one reason string, logged
  once. Absorbs `grind_episode._end_reason` and `grind.stall_hold_holds`.
- The gym hold becomes `training()` + Exit: `gym_hold_seen` and `floor_unmet` turn into derived properties, then are deleted.
  Ledger/measure/drill logging stay, called by the controller at session end.

Data flow: engine tick -> `TrainingController.tick` reads (party, maps, floor verdict, bag) -> Target / Roster / Sustain /
Exit -> writes `TrainingState` once -> plan_goal, frontier, party_order, retreat_heal, goal_talk only query the facade.

Absorb / adapt / delete: delete `train_target.py`, `grind_heal.py`, `after_heal.py` (into Sustain) and `OutsideSet` (into
`allowed_maps`); shrink `grind_episode.py` (287) to ledger + logging; plan_goal only loses lines (the :133 branch becomes
`controller.step_toward`); frontier ~154 reads `allowed_maps()`; `center_visit` and `grass_pace` unchanged.

## 3. Migration (each slice independently mergeable, A/B on seed 12)

1. **Controller as single owner, behaviour-preserving.** Add state/controller/adapters; `tick` computes the same
   `train_route_live`, episode, `gym_hold_seen`, `floor_unmet`, `train_need` values from the existing code, and the old
   attributes read from it. Net lines in plan_goal/context <= 0. A/B gate: identical decisions.jsonl.
2. **Target (highest value: 46% of steps sit under a phantom pin).** Reject unreachable / never-visited points; one target per session. Expect phantom-VF starts -> 0.
3. **Sustain.** Fold `grind_heal`, the planner heal inputs and `after_heal`; leave-center hint. Expect heal + leave-PC down.
4. **Roster.** Session-boundary reorders, two-trainee cap, `team_sig` without the fainted bit. Expect reorder sessions ~0.
5. **Exit + gym hold.** Fold `_end_reason` / stall hold; delete the `gym_hold_seen` / `floor_unmet` flags and dead modules.

## 4. Acceptance (same seed-12, 12000-step run; `uv run python tools/step_budget.py <run>`)

Baseline: Route 24 210 xp/1k, SHAKE 7.2% (862), heal 7.5% + leave-PC 5.4% = 12.9%, 42 reorder sessions, 13 episode starts.
- Route 24 xp/1k >= 210; SHAKE <= 7.2% (aim <= 5%); heal + leave-PC < 12.9% combined; reorder sessions inside a Pokecenter
  = 0 and total <= 5; episode starts on never-visited maps = 0.
- No regression on time to beat_misty. beat_misty is not reached in 12000 steps today, so the metric is floor progress: the
  two floor members reach L19 no later (levels.jsonl step) and blackouts do not rise.
- Unit tests: target (rejects unreachable point; stable across ticks; respects stage_maps); roster (lowest trainee leads;
  no order on a fainted flip; cap of two); sustain (survival floor vs Potion vs walk; hint set); exit_rule (floor met for N,
  budget, blackout, timeout); controller (tick idempotent per step; facade queries agree); plus the existing grind_episode,
  train_route and party_order tests ported. Targeted files on the laptop; the full suite runs in the cloud verify (merge gate).

## 5. Risks / what NOT to do
- Do not add lines to context.py, memory.py, plan_goal.py (300) or battle.py (299); state lives in `ctx.__dict__["training"]`.
- Do not change behaviour in slice 1; do not merge slices 2-5 without a seed-12 A/B and a clean-worktree verify.
- Risk: running `tick` before behaviours changes flag timing (the stale-flag bug class): test that readers never see
  last-step values.
- Risk: session-boundary reorders delay the lowest-first lead in a long session; mitigate by also allowing the boundary on a level-up.
- Do not delete `grind.points.choose` or the ledger: reuse as the scoring function.
- Real-ROM gate applies before explorer merges; this doc itself ran no emulator.
- Not designed here: the Mart/restock errand (102 steps); revisit after Sustain.
