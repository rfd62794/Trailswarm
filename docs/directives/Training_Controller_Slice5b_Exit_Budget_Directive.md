# PokeAgent: Training Controller slice 5b (Exit: the grind budget, stall hold and lifted-gate block) - fold GrindBudget, stall_hold_holds, the gate_lifted / lifted_need block and the episode limit checks into `src/pokeagent/explorer/training_ctl/exit_rule.py`; delete what loses its last writer; byte-identical on the real ROM

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/training-controller-2026-11-13.md` (sections 2 "Exit", 3, 4 item 5, "Invariant: the floor holds without a ledger", 5, 6 and "Slice 3 result") and `docs/directives/Training_Controller_Slice5_Exit_Hold_Directive.md` (slice 5a, which names this slice). **Depends on slice 5a**: `src/pokeagent/explorer/training_ctl/exit_rule.py` must exist and hold `publish_hold`, `publish_floor`, `floor_unmet`, `hold_clear`, `floor_hold`. **If `src/pokeagent/explorer/training_ctl/exit_rule.py` is absent in your worktree, stop immediately and write "slice 5a not merged" in the Status row.** Do not recreate it. Base: current main containing 5a. Paths are written in full from the repo root.

The plan's slice 5 reads: "**Exit + gym hold.** Fold `_end_reason`, stall hold, GrindBudget; delete `gym_hold_seen` (`behaviours/plan_goal.py:82`, :149) and the gate_lifted block (:139-151, :283, :297-298; est. -20), `floor_unmet` (`training.py:125`), then `explorer/context.py` fields :124, :165, :187 (-3) once their last writer is gone, and dead modules." Slice 5a did the two hold FLAGS. **This is slice 5b: fold `GrindBudget`, `stall_hold_holds`, the `gate_lifted` / `lifted_need` block and `grind_episode._end_reason` into `src/pokeagent/explorer/training_ctl/exit_rule.py`, and delete the old definitions and field that lose their last writer.**

## 1. Why this exists

After 5a the Exit sub-system owns two flags but not the thing that decides them: the grind budget and the stall hold still live as loose code in `src/pokeagent/explorer/grind.py`, an inline 15-line block in `src/pokeagent/explorer/behaviours/plan_goal.py`, a `ctx.grind` field in `src/pokeagent/explorer/context.py`, and the limit checks inside `src/pokeagent/explorer/grind_episode.py`'s `_end_reason`. Plan section 1: "the stall-hold/`gate_lifted`/`lifted_need` state" is one of the "several writers" that make the gym hold unreadable; plan section 4 item 5 says to fold it. `src/pokeagent/explorer/behaviours/plan_goal.py` (298 lines, cap 300) and `src/pokeagent/explorer/context.py` (300, cap 300) are at their caps, so this fold is also the slice that gives the lines back.

Slice 3's lesson, binding here (plan section 6 and "Slice 3 result"): **a "move" slice must keep `decisions.jsonl` byte-identical on the real ROM; never change the timing or order of anything guards or behaviours read.** Everything below is a same-point, same-value move. You cannot prove byte-identity (no ROM); the controller does (section 5). Your proof is oracle tests that copy the old code and compare, plus the unchanged gate.

## 2. Scope (files, in order)

1. `src/pokeagent/explorer/training_ctl/exit_rule.py` (extend the 5a module; hard cap **170 lines total**; the one new import is shown in 3.1) + NEW `tests/test_training_ctl_exit_budget.py`.
2. `src/pokeagent/explorer/grind.py` (definitions move out), `src/pokeagent/explorer/behaviours/plan_goal.py`, `src/pokeagent/explorer/grind_episode.py`, `src/pokeagent/explorer/context.py` (delete ONE field line).
3. Test import adaptations only, in: `tests/test_grind.py`, `tests/test_team_floor.py`, `tests/test_training_v2_slice2.py`, `tests/test_grind_pressure_plan_goal.py`, and the 5a file `tests/test_training_ctl_exit.py` (its `from pokeagent.explorer.grind import STALL_HOLD_CAP` line).

Touch nothing else. **No file is deleted by this slice** (deletion is refused in your sandbox): every removal is an edit inside a file that stays. If you find a module that would be dead after your change, leave the file and list it in your report; the controller deletes it in review.

**Line budget:** `src/pokeagent/explorer/behaviours/plan_goal.py` net lines <= 0 (expected about -12); `src/pokeagent/explorer/context.py` net exactly -1; `src/pokeagent/explorer/grind_episode.py` net <= 0. Check `git diff --stat origin/main`.

## 3. The work

### Current code (verified on main, 2026-11-14, BEFORE 5a merged; re-check every line number with the greps in section 5, 5a shifts a few lines and the merged file wins)

`src/pokeagent/explorer/grind.py`: constants `GRIND_BATTLES = 25`, `GRIND_BATTLES_GYARADOS = 120`, `GRIND_STEPS = 2500`, `GRIND_BLACKOUTS = 2`, `CEILING_MARGIN = 6` at the top (STAY in `src/pokeagent/explorer/grind.py`: several modules and tests import them); `stall_keeps_hold` (:23); `STALL_HOLD_CAP = 6000`, `FLOOR_CAP_MULT = 3`, `FLOOR_BLACKOUTS = 10` (:41-43); `stall_hold_holds` (:46-56); `class GrindBudget` (:99-137: `__init__` with `_s` and `_lifted`, `lifted`, `reason`, `update`). Everything else in the file (`best_level`, `grinding_now`, `battle_outcome`, `outcome_of`, `record_battle_result`) STAYS.

`src/pokeagent/explorer/behaviours/plan_goal.py` (line numbers are pre-5a; 5a has since edited :83, :87, :141, :147 in place):
```python
:14  from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BATTLES_GYARADOS, GrindBudget, best_level, grinding_now, stall_hold_holds, STALL_HOLD_CAP
:135-138      if st.get("stall_hold_goal") not in (None, ctx.stage_goal):
                  st.pop("stall_hold", None)  # ...comment
                  st.pop("lifted_need", None)  # ...comment
              st["stall_hold_goal"] = ctx.stage_goal
:139          lifted = st.get("gate_lifted") is not None
:140-141      if hold and not stall_hold_holds(st, ctx.grind.reason(st["gate_lifted"]) if lifted else "without a level gain",
                                               ctx.step, party_log.of(ctx).blackouts, <5a: exit_rule.floor_unmet(ctx)>):  # monotonic blackouts
:142-146          hold = False  # ...
                  if st.get("gate_skip_logged") != ctx.stage_goal:
                      st["gate_skip_logged"] = ctx.stage_goal
                      why = ctx.grind.reason(st["gate_lifted"]) if lifted else f"held {STALL_HOLD_CAP} steps or a blackout"
                      ctx.log(f"[team gate: grind budget spent ({why}); gym hold lifted for {ctx.stage_goal}]", "res")
:147          <5a: exit_rule.publish_hold(ctx, hold)>
:148-149      if hold and st.get("gate_lifted") is not None:
                  ctx.train_need = st.get("lifted_need") or ctx.train_need  # the budget stops forcing, not forbids: episodes may start
:150          if hold:        <- NOT part of the block; it and everything after stay
:281          st["gate_lifted"] = None                                  (in PlanGoal._budgeted)
:288          ctx.grind = ctx.grind or GrindBudget()
:289-291      why = ctx.grind.update(goal, level=level, step=ctx.step, battles=ctx.battles, blackouts=ctx.blackouts_row,
                                   training=0 < level < need and grinding_now(ctx), ceiling=level_ceiling(stage),
                                   max_battles=GRIND_BATTLES_GYARADOS if tr else GRIND_BATTLES)
:292-293      if why: ctx.log(f"[readiness] grind budget spent for {goal}: {why}; lifting the training gate", "res")
:294-297      if ctx.grind.lifted(goal):
                  st["gate_lifted"] = goal
                  st["lifted_need"] = need  # a held gym still wants this level: the episode gate reads it back
                  return 0
```
`src/pokeagent/explorer/grind_episode.py` (callers of `_end_reason` at :132 and :193 stay as they are):
```python
:26  from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BLACKOUTS, GRIND_STEPS   # used ONLY by _end_reason
:209 def _end_reason(ctx, ep: dict) -> str | None:
         if ctx.view.battling or ctx.in_battle: return None
         lvl = _lvl_of(ctx, _levels(ctx), ep["slot"])
         if lvl >= ep["need"]: return f"trainee reached L{ep['need']}"
         if not getattr(ctx, "train_need", 0): return "the training gate lifted"
         if not _trainee_ok(ctx): return "the trainee is not fit to train"
         pl = party_log.of(ctx)
         if pl.blackouts - ep["blackouts0"] >= GRIND_BLACKOUTS: return f"{GRIND_BLACKOUTS} blackouts"
         if ctx.battles - ep["battles0"] >= GRIND_BATTLES: return f"{GRIND_BATTLES} battles"
         if ctx.step - ep["start_step"] >= GRIND_STEPS: return f"{GRIND_STEPS} steps"
         if sustain.hurt_no_potion(ctx): return "hurt with no potion"
         pt = ep.get("point") ... (story-blocker check)  return None
```
`src/pokeagent/explorer/context.py:113`: `grind: Any = None         # explorer.grind.GrindBudget, made on first use`. Its only writer is `src/pokeagent/explorer/behaviours/plan_goal.py:288`; its only src readers are `src/pokeagent/explorer/behaviours/plan_goal.py:140`, `:145`, `:289`, `:294` (verified by `git grep`). Tests read `ctx.grind` only on `SimpleNamespace` fixtures that pass `grind=None` (`tests/test_grind.py:118,136,176,179,192`, `tests/test_team_readiness.py:165,237`): those keep working unchanged because the budget is stored under the SAME name in `ctx.__dict__` (below).

**Fields the plan lists that are NOT deleted here:** the plan's `src/pokeagent/explorer/context.py` ":124, :165, :187" are `train_route_live`, `train_need`, `train_member`. Slice 3 made `src/pokeagent/explorer/training_ctl/training_ctl/sustain.py` `publish` the writer of `train_route_live`, and `src/pokeagent/explorer/behaviours/plan_goal.py` still writes `train_need` and `train_member`; they have readers in `src/pokeagent/explorer/grind_episode.py`, `src/pokeagent/explorer/party_log.py`, `src/pokeagent/explorer/par_follow.py` and the shadow `src/pokeagent/explorer/training_ctl/training_ctl/adapters.py`. They do NOT lose their last writer in this slice: leave all three. Likewise `gym_hold_seen` and `floor_unmet` keep their names and shapes (5a made `src/pokeagent/explorer/training_ctl/exit_rule.py` their only writer; `src/pokeagent/explorer/behaviours/goal_talk.py`, `src/pokeagent/explorer/behaviours/frontier.py` and the shadow still read them). Report the grep evidence for all five.

### 3.1 `src/pokeagent/explorer/training_ctl/exit_rule.py` (grows; cap 170 lines total)

Add exactly one import block after `from __future__ import annotations`: `from pokeagent.explorer.grind import CEILING_MARGIN, GRIND_BATTLES, GRIND_BLACKOUTS, GRIND_STEPS`. (`src/pokeagent/explorer/grind.py` imports only `pokeagent.knowledge.blackout_tax`, so no cycle; `src/pokeagent/explorer/grind.py` must NOT import `exit_rule`.) Then:

1. **Moved verbatim from `src/pokeagent/explorer/grind.py`** (copy the bodies and docstrings, do not rewrite; change nothing but where they live): `stall_keeps_hold`, the three constants `STALL_HOLD_CAP`, `FLOOR_CAP_MULT`, `FLOOR_BLACKOUTS` (with their comments), `stall_hold_holds`, `class GrindBudget`. Then delete those definitions from `src/pokeagent/explorer/grind.py` (an edit inside the file; the file stays). Fix the module docstring of `src/pokeagent/explorer/grind.py` only if it names something you moved.
2. `def budget(ctx) -> GrindBudget`: `b = ctx.__dict__.get("grind")`; if it is `None`, `b = ctx.__dict__["grind"] = GrindBudget()`; return `b`. It is the exact equivalent of the old `ctx.grind = ctx.grind or GrindBudget()` (a `GrindBudget` is always truthy). The key stays `"grind"` on purpose (see above).
3. `def clear_lift(st: dict) -> None`: `st["gate_lifted"] = None` (old :281). `def record_lift(st: dict, goal: str, need: int) -> None`: `st["gate_lifted"] = goal; st["lifted_need"] = need` in that order (old :295-296). The dict keys keep their names: `tests/test_grind_pressure_plan_goal.py:189` reads `team_plan.of(ctx).get("gate_lifted")` and `:211-223` read `st["stall_hold"]`, and the team-plan state is shared storage.
4. `def settle_hold(ctx, st: dict, hold: bool, blackouts) -> bool`: the old plan_goal block :135-149, moved VERBATIM into this function, returning `hold` at the end. `blackouts` is a ZERO-ARGUMENT CALLABLE, and the call site passes `lambda: party_log.of(ctx).blackouts`. This matters: in the old code `party_log.of(ctx).blackouts` sat inside `if hold and not stall_hold_holds(...)`, so it was evaluated only when `hold` was truthy; passing the value would evaluate `party_log.of(ctx)` on every step and could change behaviour. Inside the function call `blackouts()` only at the same place the old code evaluated it (`hold and not stall_hold_holds(..., blackouts(), floor_unmet(ctx))`, same operand order). Use `budget(ctx).reason(st["gate_lifted"])` where the old code said `ctx.grind.reason(st["gate_lifted"])` (it is only reached when `lifted` is true, so `budget(ctx)` never creates one there that the old code would not have had). Keep: the `st.pop("stall_hold", None)` / `st.pop("lifted_need", None)` pair under the `stall_hold_goal` check, the `st["stall_hold_goal"] = ctx.stage_goal` line, the `gate_skip_logged` log with its exact message text, then `publish_hold(ctx, hold)` (5a's function, at the same point the old `:147` assignment sat: AFTER the stall verdict, BEFORE the `train_need` line), then the `if hold and st.get("gate_lifted") is not None: ctx.train_need = st.get("lifted_need") or ctx.train_need` lines with their comment. Same `ctx.log(..., "res")` tag and message strings.
5. Two pure functions for the episode limits (the checks of `_end_reason` that need no ctx), message strings character-for-character as above:
   - `def episode_gate(lvl: int, need: int, train_need) -> str | None`: `if lvl >= need: return f"trainee reached L{need}"`; `if not train_need: return "the training gate lifted"`; else `None`.
   - `def episode_spent(*, blackouts: int, battles: int, steps: int) -> str | None`: `blackouts >= GRIND_BLACKOUTS` -> `f"{GRIND_BLACKOUTS} blackouts"`; then `battles >= GRIND_BATTLES` -> `f"{GRIND_BATTLES} battles"`; then `steps >= GRIND_STEPS` -> `f"{GRIND_STEPS} steps"`; else `None`. (Arguments are the DELTAS since the episode start.)
   Update the module docstring: Exit sub-system after 5b: owns the hold flags, the grind budget, the stall hold, the lifted-gate state and the episode limits; the unfinished remainder is `area_grind` caps and `grinding_now`, which stay where they are.

### 3.2 The moves (commit 1, subject `Exit 5b: fold the grind budget, stall hold and lifted gate into exit_rule (no behaviour change)`)

- `src/pokeagent/explorer/behaviours/plan_goal.py`: the line-14 import loses `GrindBudget`, `stall_hold_holds`, `STALL_HOLD_CAP` (edit the line in place: it keeps `GRIND_BATTLES, GRIND_BATTLES_GYARADOS, best_level, grinding_now`); `exit_rule` is already imported by 5a. Replace the block of old :135-149 with ONE statement at the same indentation and the same point: `hold = exit_rule.settle_hold(ctx, st, hold, lambda: party_log.of(ctx).blackouts)`. In `_budgeted`: `:281` -> `exit_rule.clear_lift(st)`; `:288` -> `bud = exit_rule.budget(ctx)`; `:289` -> `why = bud.update(` (same arguments, same continuation lines); `:294-297` -> `if bud.lifted(goal):` / `exit_rule.record_lift(st, goal, need)` / `return 0`. After the edit `src/pokeagent/explorer/behaviours/plan_goal.py` has no `gate_lifted`, `lifted_need`, `stall_hold`, `GrindBudget` or `ctx.grind` text.
- `src/pokeagent/explorer/grind_episode.py`: delete the line-26 import (its three names are used only inside `_end_reason`); add `exit_rule` to the existing `from pokeagent.explorer.training_ctl import roster, sustain, target` line. `_end_reason` keeps its name, signature, callers and the position of every check; its body becomes: the battling guard; `lvl = _lvl_of(...)`; `why = exit_rule.episode_gate(lvl, ep["need"], getattr(ctx, "train_need", 0))` and return it when set; the `_trainee_ok` check unchanged; `pl = party_log.of(ctx)`; `why = exit_rule.episode_spent(blackouts=pl.blackouts - ep["blackouts0"], battles=ctx.battles - ep["battles0"], steps=ctx.step - ep["start_step"])` and return it when set; then the `hurt_no_potion` and story-blocker checks UNCHANGED. The `_trainee_ok`, `hurt_no_potion` and story-blocker checks stay where they are because they need ctx and sit between the folded ones; do not reorder anything.
- `src/pokeagent/explorer/context.py`: delete the single line 113 (`grind: Any = None ...`). Then check whether `Any` is still used in the file (`git grep -n "Any" -- src/pokeagent/explorer/context.py`): the other fields almost certainly still use it; leave the import alone if so. Net -1, no other edit.
- `src/pokeagent/explorer/grind.py`: delete the moved definitions only (3.1 item 1). If `blackout_tax` is still used by `record_battle_result` (it is), keep that import.
- Test import adaptations (the only source-text-free edits to existing tests): `tests/test_grind.py:10` drop `GrindBudget` from the `explorer.grind` import and add `from pokeagent.explorer.training_ctl.exit_rule import GrindBudget`; `:128` and `:147` import `stall_keeps_hold` from `pokeagent.explorer.training_ctl.exit_rule` instead (keep `best_level` on the grind import); `:156` import `STALL_HOLD_CAP, stall_hold_holds` from `exit_rule`. `tests/test_team_floor.py:99` and `tests/test_training_v2_slice2.py:10` and `tests/test_grind_pressure_plan_goal.py:183`: the same names now from `pokeagent.explorer.training_ctl.exit_rule`. `tests/test_training_ctl_exit.py`: its `STALL_HOLD_CAP` import the same way. Change nothing else in those files; every assertion stays.

### 3.3 Tests (commit 2, subject `Exit 5b: oracle tests for the folded budget and stall hold`; file `tests/test_training_ctl_exit_budget.py`)

Use `SimpleNamespace` contexts (`step`, `stage_goal`, `train_need`, `log=lambda t, tag=None: logs.append((t, tag))`) as `tests/test_training_ctl_sustain.py` does. Required:
1. `test_budget_is_lazy_and_stored_under_grind`: `budget(ctx)` creates one `GrindBudget`, returns the same object on a second call, stores it at `ctx.__dict__["grind"]`; a ctx built with `grind=None` also works; a pre-set instance is returned untouched.
2. `test_settle_hold_matches_the_old_block` (the byte-identity oracle): put a verbatim copy of the OLD block (the five lines `stall_hold_goal` .. `ctx.train_need`, with `ctx.grind.reason` and `stall_hold_holds` taken from `exit_rule` and `ctx.gym_hold_seen = (ctx.step, bool(hold))` for the flag) in the test as `_old_block(ctx, st, hold, blackouts_value)`. Drive both with deep-copied identical `st` and ctx over the full matrix: `hold` in (True, False); `gate_lifted` set (with a `budget(ctx)` lifted for that goal via `update` past the cap, reason "2500 steps without a level gain") or None; `floor_unmet` in (True, False) via `publish_floor`; steps `0`, `STALL_HOLD_CAP - 1`, `STALL_HOLD_CAP`, `STALL_HOLD_CAP * FLOOR_CAP_MULT`; blackouts `0`, `1`, `FLOOR_BLACKOUTS`; a stage change between two calls (`stall_hold_goal` differs). Assert equal returned `hold`, equal `st`, equal `ctx.gym_hold_seen`, equal `ctx.train_need`, equal `logs`.
3. `test_settle_hold_blackouts_callable_is_lazy`: with `hold=False`, the callable is never called; with `hold=True` it is called exactly once per `settle_hold` call.
4. `test_clear_and_record_lift_keys`: `clear_lift` sets `gate_lifted` to `None` and leaves `lifted_need`; `record_lift(st, "beat_brock", 14)` gives `gate_lifted == "beat_brock"` and `lifted_need == 14`.
5. `test_episode_gate_and_spent_strings_and_order`: `episode_gate(10, 10, 5) == "trainee reached L10"` and a lower level with `train_need=0` gives `"the training gate lifted"`; reaching the level wins over a lifted gate; `episode_spent` gives the three strings at the exact thresholds (`GRIND_BLACKOUTS`, `GRIND_BATTLES`, `GRIND_STEPS`, and `None` one below each), blackouts before battles before steps when several are met.
6. `test_old_definitions_are_gone`: `not hasattr(pokeagent.explorer.grind, "GrindBudget")` and the same for `stall_hold_holds`, `stall_keeps_hold`, `STALL_HOLD_CAP`, `FLOOR_CAP_MULT`, `FLOOR_BLACKOUTS`; `inspect.getsource(plan_goal)` contains none of `GrindBudget`, `stall_hold_holds`, `lifted_need`, `"gate_lifted"`, `ctx.grind`; `"grind" not in {f.name for f in dataclasses.fields(ExplorerContext)}` (import `ExplorerContext` from `pokeagent.explorer.context`).
7. `test_exit_floor_holds_with_empty_ledger` (5a's test) must still pass unchanged; do not edit it beyond the import line.

## 4. What NOT to do

- No ROM, no emulator process, no `runs/` access (absent in your worktree; do not look). Tests use `SimpleNamespace` / `tmp_path` and the existing fixtures only.
- **No timing or order change.** Every write and read stays at the exact point it was at; `publish_hold` stays after the stall verdict and before the `train_need` line; the blackouts value stays lazy; `budget(ctx)` is created at the same line the old `ctx.grind = ...` ran. No behaviour change: if a test needs a decision to change, stop and report.
- Do NOT delete a file, and do not ask for one to be deleted by anything but the controller: list any would-be-dead module in the report. Do NOT delete `gym_hold_seen`, `floor_unmet`, `train_route_live`, `train_need`, `train_member` (section 3, "NOT deleted here").
- Do not touch `src/pokeagent/explorer/area_grind.py` (its steps/battles caps are a later piece of Exit), `grinding_now`, `best_level`, `src/pokeagent/explorer/planner*.py`, `src/pokeagent/knowledge/team_floor.py`, `src/pokeagent/explorer/behaviours/guards.py` (the loop guard), `src/pokeagent/explorer/training_ctl/adapters.py`, `src/pokeagent/explorer/training_ctl/controller.py`, `src/pokeagent/explorer/training_ctl/state.py`, `src/pokeagent/explorer/training_ctl/sustain.py`, `src/pokeagent/explorer/training_ctl/target.py`, `src/pokeagent/explorer/training_ctl/roster.py`, `src/pokeagent/explorer/behaviours/goal_talk.py`, `src/pokeagent/explorer/behaviours/frontier.py`, `src/pokeagent/explorer/training.py`. Do not change `FLOOR_CAP_MULT`, `FLOOR_BLACKOUTS`, `STALL_HOLD_CAP` values, any message string, or the `GRIND_*` constants.
- No lines added to `src/pokeagent/explorer/behaviours/plan_goal.py` net or `src/pokeagent/explorer/context.py`; no new log lines, no new `decisions.jsonl` rows, no new files in a run dir, no new dependency, no new module (everything goes into `src/pokeagent/explorer/training_ctl/exit_rule.py`; if it would pass 170 lines, stop and write the count in the Status row instead of splitting it).

## 5. Verification (exact commands, from the worktree root)

Baseline first. Claude ran this on main before 5a merged (2026-11-14): `169 passed, 1 warning in 12.31s`. With 5a merged the count is that plus 5a's new tests: **record the number you see before your first edit; after part 1 it must be the same number** (adapted imports only).
```
uv run pytest -q -p no:cacheprovider tests/test_grind.py tests/test_area_grind.py tests/test_grind_pressure_plan_goal.py tests/test_plan_goal_gym_road.py tests/test_goal_talk.py tests/test_training_v2_slice2.py tests/test_team_floor.py tests/test_team_readiness.py tests/test_grind_episode.py tests/test_training_ctl_*.py tests/test_frontier_patrol.py
```
Expected: 0 failed. If not, stop and write the failing ids; do not fix them.

After commit 1 run the same command again (same count, 0 failed). After commit 2:
```
uv run pytest -q -p no:cacheprovider tests/test_training_ctl_exit_budget.py tests/test_training_ctl_exit.py
```
Expected: all pass, none skipped.
```
wc -l src/pokeagent/explorer/training_ctl/exit_rule.py src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py src/pokeagent/explorer/grind_episode.py src/pokeagent/explorer/grind.py
git diff --stat origin/main
git grep -n "GrindBudget\|stall_hold_holds\|stall_keeps_hold\|STALL_HOLD_CAP\|lifted_need\|gate_lifted" -- src
git grep -n "train_route_live\|train_need\|train_member\|gym_hold_seen\|floor_unmet" -- src
```
Expected: `src/pokeagent/explorer/training_ctl/exit_rule.py` <= 170; `src/pokeagent/explorer/behaviours/plan_goal.py` <= its pre-edit count (net <= 0); `src/pokeagent/explorer/context.py` exactly one line fewer than before (299 if it was 300); the stat lists only `src/pokeagent/explorer/training_ctl/exit_rule.py`, `src/pokeagent/explorer/grind.py`, `src/pokeagent/explorer/behaviours/plan_goal.py`, `src/pokeagent/explorer/grind_episode.py`, `src/pokeagent/explorer/context.py`, the new test and the adapted tests of section 2.3; the first grep shows those names defined/used only in `src/pokeagent/explorer/training_ctl/exit_rule.py` (plus comments and the dict KEYS `"gate_lifted"` / `"lifted_need"` inside `src/pokeagent/explorer/training_ctl/exit_rule.py`, and docstrings); the second grep is evidence for the five fields you did NOT delete (paste it).

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`; about 3 minutes):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (main before 5a was `2951 passed, 63 skipped` on 2026-11-14; yours is that plus 5a's and later merges' tests plus your new ones; skip count unchanged).

**Not yours (the controller, on the laptop, after review):** the real-ROM proof that this is a pure move. `decisions.jsonl` from a 12000-step seed 12 run and a seed 13 run from `heal_cerulean` must be BYTE-IDENTICAL to main (the bar slices 3 and 5a met), `tools/step_budget.py` rows unchanged, and the shadow controller's `mismatches` empty. The controller also deletes any module you list as dead. You cannot prove any of that; do not claim it.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the worktree. Do not search, glob or hunt for missing things: if something named here is missing or has moved, stop and write why in the Status row (a line number that drifted by a few lines is NOT missing: use the grep). Never use `python -c`.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Never delete files. Create no scratch or debug files.
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/training-controller-slice5b-exit-budget`; commit as you go (two commits as in section 3) and push the branch.
- No ROM, no `runs/` access.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with both commits and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `src/pokeagent/explorer/training_ctl/exit_rule.py` holds `GrindBudget`, `stall_keeps_hold`, `stall_hold_holds`, the three stall constants, `budget`, `clear_lift`, `record_lift`, `settle_hold`, `episode_gate`, `episode_spent`, <= 170 lines; `src/pokeagent/explorer/grind.py` no longer defines the moved names. <!-- test: tests/test_training_ctl_exit_budget.py::test_old_definitions_are_gone -->
- [ ] The old plan_goal block is one `settle_hold` call and behaves identically for the whole matrix. <!-- test: tests/test_training_ctl_exit_budget.py::test_settle_hold_matches_the_old_block -->
- [ ] The blackouts value stays lazy. <!-- test: tests/test_training_ctl_exit_budget.py::test_settle_hold_blackouts_callable_is_lazy -->
- [ ] `ExplorerContext` has no `grind` field and `src/pokeagent/explorer/behaviours/plan_goal.py` has no `ctx.grind`; the five other fields and flags are untouched.
- [ ] `_end_reason` keeps its name, callers and check order; the folded checks give the same strings. <!-- test: tests/test_training_ctl_exit_budget.py::test_episode_gate_and_spent_strings_and_order -->
- [ ] `src/pokeagent/explorer/behaviours/plan_goal.py` net <= 0, `src/pokeagent/explorer/context.py` exactly -1, no file deleted, no 5a-owned test weakened.
- [ ] Baseline gate (same count before and after), new tests and the full suite: 0 failed.

## 8. Report

Findings first: `wc -l` of the five files; the two `git grep` outputs; the per-file diff stat; every line number that differed from section 3 (the merged files win); whether the oracle test passed on first run; any module that is now dead (list it, do not delete it); and a plain statement of which of the plan's listed deletions you did NOT do and why (`train_route_live`, `train_need`, `train_member`, `gym_hold_seen`, `floor_unmet`, `area_grind` caps). Then the real output tails: baseline gate, after-commit-1 gate, new tests, the full-suite line. State plainly that no ROM was used and that the byte-identical seed 12/13 `decisions.jsonl` proof is the controller's, run on the laptop after review.

## Required from User

Nothing for the build. Queue only after slice 5a has merged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/training-controller-2026-11-13.md)
- Read(src/pokeagent/explorer/training_ctl/exit_rule.py)
- Read(src/pokeagent/explorer/grind.py)
- Read(src/pokeagent/explorer/grind_episode.py)
- Read(src/pokeagent/explorer/behaviours/plan_goal.py)
- Read(src/pokeagent/explorer/context.py)
- Read(tests/test_training_ctl_sustain.py)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)
