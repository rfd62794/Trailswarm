# PokeAgent: Training Controller slice 5a (Exit: the gym-hold and floor flags) - one writer and one set of readers for `gym_hold_seen` and `floor_unmet`; pin "the floor holds without a ledger"

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/training-controller-2026-11-13.md` (sections 2 "Exit", 3, 4 item 5, "Invariant: the floor holds without a ledger", 5, 6 and "Slice 3 result"). **Depends on slice 4 (Roster) = PR #263 being merged**: `src/pokeagent/explorer/training_ctl/roster.py` must exist. **If `src/pokeagent/explorer/training_ctl/roster.py` is absent in your worktree, stop immediately and write "slice 4 (#263) not merged" in the Status row.** Do not recreate it. Merged already: slices 1 (shadow), 2 (Target, #250), 3 (Sustain, #259): `explorer/training_ctl/{state,controller,adapters,target,sustain}.py`. Base: current main containing #263. All paths below are under `src/pokeagent/` unless they start with `tests/`, `tools/` or `docs/`.

The plan's slice 5 reads: "**Exit + gym hold.** Fold `_end_reason`, stall hold, GrindBudget; delete `gym_hold_seen` (`behaviours/plan_goal.py:82`, :149) and the gate_lifted block (:139-151, :283, :297-298; est. -20), `floor_unmet` (`training.py:125`), then `explorer/context.py` fields :124, :165, :187 (-3) once their last writer is gone, and dead modules."

**That is too large for one reviewable, byte-identical slice, so it is split. This directive is slice 5a: the two hold FLAGS only** (`gym_hold_seen`, `floor_unmet`): one writer module, every reader through it, no timing change, plus the plan's empty-ledger invariant test. **Slice 5b (later, NOT yours): fold `GrindBudget`, `stall_hold_holds`, the `gate_lifted` / `lifted_need` block and `grind_episode._end_reason` into the same module and delete the old flags.** Do not start 5b.

## 1. Why this exists

Seed 12, heal_cerulean -> beat_misty, 12000 steps (plan section 1): beat_misty was not reached with party L8-10 x5 + L25 against a floor of L19 for 2 members. The "gym hold" (the boss is held shut while the team is not ready) is today a pair of ad-hoc ctx fields with several writers and readers, all re-derived at different points of a step:

- `ctx.gym_hold_seen = (step, bool)`: written at `explorer/behaviours/plan_goal.py:83` (the fainted-trainee early return, `(ctx.step, True)`) and `:147` (`(ctx.step, bool(hold))`, after the stall-hold verdict). Read at `explorer/behaviours/goal_talk.py:60` (`_hold_clear`) and `explorer/behaviours/frontier.py:151` (`floor_hold`); and by the shadow side `explorer/training_ctl/adapters.py:18` (`old_flags`, left as is: it is the "old flags" half of the shadow compare).
- `ctx.__dict__["floor_unmet"]`: written at `explorer/training.py:125` in `gate_state`; read at `plan_goal.py:87` and `:141`, and `frontier.py:151`.

Slice 3's lesson, binding here (plan section 6): **a "move" slice must keep `decisions.jsonl` byte-identical on the real ROM; never change the timing or order of a flag that guards or behaviours read.** So 5a moves only WHO writes and reads these two flags, to the exact same points, with the exact same values. The plan's "Invariant: the floor holds without a ledger" gets a regression test written FIRST (section 3.3): Claude checked on current main that its behaviour already holds, so it is a pin, not a fix.

## 2. Scope (files, in order)

1. NEW `explorer/training_ctl/exit_rule.py` (< 70 lines, no imports beyond `__future__`) + NEW `tests/test_training_ctl_exit.py`.
2. Part (a), ONE commit (decisions MUST stay identical): `explorer/behaviours/plan_goal.py`, `explorer/training.py`, `explorer/behaviours/goal_talk.py`, `explorer/behaviours/frontier.py`; test adaptation of two source-text assertions: `tests/test_goal_talk.py`, `tests/test_training_v2_slice2.py`.
3. Part (b), ONE commit, test-only: `tests/test_training_ctl_exit.py` gets `test_exit_floor_holds_with_empty_ledger` (the plan's regression test).

Touch nothing else. `plan_goal.py` is 298 lines (cap 300) and `explorer/context.py` is 300: **net lines added to `plan_goal.py` must be <= 0 and to `context.py` exactly 0** (check `git diff --stat`).

## 3. The work

### Current code (verified on main, 2026-11-14; re-check line numbers with `git grep -n "gym_hold_seen\|floor_unmet" -- src`, they may drift by a few lines after #263, and the merged file wins)

`plan_goal.py`:
```python
:17  from pokeagent.explorer.training_ctl import sustain          # shared import line: extend it, do not add a line
:83      ctx.gym_hold_seen = (ctx.step, True); return None  # not judged this step: goal_talk must not walk to the leader meanwhile ...
:87      elif team.ready and not ctx.__dict__.get("floor_unmet"):  # the sim alone must not settle the stage while the team floor is unmet
:140-141 if hold and not stall_hold_holds(st, ctx.grind.reason(st["gate_lifted"]) if lifted else "without a level gain",
                                          ctx.step, party_log.of(ctx).blackouts, ctx.__dict__.get("floor_unmet", False)):  # monotonic blackouts
:147     ctx.gym_hold_seen = (ctx.step, bool(hold))  # goal_talk reads this: a gym leader is only walked to when no hold is active
```
`training.py:125` (in `gate_state`): `ctx.__dict__["floor_unmet"] = floor is not None and not floor.met  # plan_goal's stall escape reads it (floor must hold)`
`goal_talk.py:58-62` (`HOLD_FRESH = 30` is defined at :24 of that file):
```python
def _hold_clear(ctx: ExplorerContext) -> bool:
    """True only when PlanGoal recently judged the gym hold NOT active ..."""
    seen = getattr(ctx, "gym_hold_seen", None)
    return bool(seen) and seen[1] is False and ctx.step - seen[0] <= HOLD_FRESH
```
`frontier.py:151`:
```python
floor_hold = bool(ctx.__dict__.get("floor_unmet")) and (getattr(ctx, "gym_hold_seen", None) or (0, False))[1]  # boss held shut by the team floor: find grass, never the leader
```
`explorer/context.py` has NO `gym_hold_seen` or `floor_unmet` field (they are set dynamically; tests set `ctx.gym_hold_seen = (100, hold)` directly, so the attribute name and tuple shape `(step, bool)` MUST NOT change). The constants (verified): `STALL_HOLD_CAP = 6000`, `FLOOR_CAP_MULT = 3`, `FLOOR_BLACKOUTS = 10` (`explorer/grind.py:41-43`).

### 3.1 `explorer/training_ctl/exit_rule.py` (< 70 lines)

```python
def publish_hold(ctx, held: bool) -> None      # the ONE writer of ctx.gym_hold_seen: ctx.gym_hold_seen = (ctx.step, bool(held))
def publish_floor(ctx, unmet: bool) -> None    # the ONE writer of the floor flag:  ctx.__dict__["floor_unmet"] = bool(unmet)
def floor_unmet(ctx) -> bool                   # bool(ctx.__dict__.get("floor_unmet"))
def hold_clear(ctx, fresh: int) -> bool        # goal_talk's rule, verbatim: seen = getattr(ctx, "gym_hold_seen", None); bool(seen) and seen[1] is False and ctx.step - seen[0] <= fresh
def floor_hold(ctx) -> bool                    # frontier's rule: floor_unmet(ctx) and the stamped hold flag (False when never stamped)
```
Module docstring: the Exit sub-system's slice 5a (flags only), naming the two attributes it owns and that 5b folds the budget. `publish_*` assign exactly what the old lines assigned (same attribute, same tuple shape, same bool coercion: `bool(hold)` at :147 already coerced; the `:83` call passes the literal `True`). `floor_hold` must return the same truthiness as the old frontier expression for every input (cover it in tests, section 3.4). No other behaviour, no logging, no state of its own.

### 3.2 Part (a): the moves (commit 1, message subject `Exit 5a: one writer and one reader set for the gym-hold flags (no behaviour change)`)

- `plan_goal.py`: `:83` -> `exit_rule.publish_hold(ctx, True); return None` with the trailing comment untouched; `:87` -> `elif team.ready and not exit_rule.floor_unmet(ctx):`; `:141` the argument `ctx.__dict__.get("floor_unmet", False)` -> `exit_rule.floor_unmet(ctx)`; `:147` -> `exit_rule.publish_hold(ctx, hold)`. Extend the existing `from pokeagent.explorer.training_ctl import sustain` line to `import exit_rule, sustain`. Every edit is in place on the same line: net 0 lines.
- `training.py:125`: `exit_rule.publish_floor(ctx, floor is not None and not floor.met)`, keep the trailing comment; add the import `from pokeagent.explorer.training_ctl import exit_rule` after line 13 (`training_ctl/__init__.py` is a docstring only and `exit_rule` imports nothing, so no cycle: `training_ctl/adapters.py` already imports `training`).
- `goal_talk.py`: `_hold_clear` body becomes `return exit_rule.hold_clear(ctx, HOLD_FRESH)` (keep its docstring and signature; tests call `_hold_clear`/set the tuple directly); add the import next to the other `explorer` imports.
- `frontier.py:151`: `floor_hold = exit_rule.floor_hold(ctx)  # <same trailing comment>`; extend the existing `from pokeagent.explorer.training_ctl import sustain` line (line 7) to `import exit_rule, sustain`.
- Do NOT touch `training_ctl/adapters.py`, `controller.py`, `state.py`: the shadow keeps reading the raw attributes (it is the independent "old flags" side of the compare) and must stay green unchanged.
- Test adaptations (the only two tests that pin the old source text): `tests/test_goal_talk.py:131` `assert "gym_hold_seen = (ctx.step, True)" in src[i - 300:i + 200]` -> `assert "exit_rule.publish_hold(ctx, True)" in src[i - 300:i + 200]`; `tests/test_training_v2_slice2.py:121` the pinned line `'elif team.ready and not ctx.__dict__.get("floor_unmet")'` -> `'elif team.ready and not exit_rule.floor_unmet(ctx)'`. Change nothing else in those files.

### 3.3 Part (b): the plan's invariant, pinned first (commit 2, subject `Exit 5a: pin the floor holds without a ledger (test only)`)

The plan: "The Exit sub-system must hold the gym approach whenever the team floor is unmet, regardless of whether a grind ledger or learned path exists. An empty ledger means Target falls back to exploring for grass and never releases the hold. Regression test: `test_exit_floor_holds_with_empty_ledger` - an empty ledger with the floor unmet produces no goal_talk/gym approach."

Claude ran this probe on current main (2026-11-14) and it PASSES, printing `0 / 50 / 6001` steps each as `Decision(button='DOWN', ... why='team gate: grinding the party')` with `gym_hold_seen == (step, True)`. Put it in `tests/test_training_ctl_exit.py` as `test_exit_floor_holds_with_empty_ledger` (imports at the top of that file: `from types import SimpleNamespace`, `from pokeagent.explorer.behaviours import plan_goal`, `from pokeagent.explorer.behaviours.plan_goal import PlanGoal`, `from pokeagent.explorer.grind import STALL_HOLD_CAP`, `from pokeagent.knowledge import team_floor`, `from test_grind_pressure_plan_goal import _full_ctx, _gate_patch`):
```python
def test_exit_floor_holds_with_empty_ledger(tmp_path, monkeypatch):
    """tmp_path has no grind_points.json / xp_spots.json / milestones.json and the maps have no learned grass: the sim says
    READY but the team floor is unmet, so the gym approach must still be held (no UP into the gym) and goal_talk must stay shut."""
    ctx = _full_ctx(tmp_path)
    _gate_patch(monkeypatch)
    nv = SimpleNamespace(ready=True, need=15, text="team ready vs MISTY", team_score=0.4, weak_slots=(), lead_slot=0)
    monkeypatch.setattr(plan_goal, "boss_need_for", lambda goals, party: nv)
    unmet = team_floor.Floor(False, 19, 2, 1, 0, "team floor for beat_misty: need 2 members >= L19, have 1")
    monkeypatch.setattr("pokeagent.explorer.training.floor_for", lambda goals, party: unmet)
    ctx.mem.data["maps"]["3"] = {"visited": {"2,4": 1}, "warps": {"2,4,UP": [0x41, 4, 6]}}   # the gym door is one press UP, no "encounters"
    for step in (0, 50, STALL_HOLD_CAP + 1):                                                  # the floor cap is STALL_HOLD_CAP * FLOOR_CAP_MULT
        ctx.step = step
        d = PlanGoal().step(ctx)
        assert d is None or d.button != "UP"
        assert ctx.gym_hold_seen == (step, True)
        assert not exit_rule.hold_clear(ctx, 30)                                              # goal_talk's gate stays shut
```
(Add `from pokeagent.explorer.training_ctl import exit_rule`.) **If this test FAILS on the part-(a) code, stop and write the real output in the Status row: that is the plan's known fresh-runs bug reproduced and it needs a design decision, not a guess.** Do not weaken it, do not add a fix in this slice. Note for the report: the floor hold is deliberately NOT forever: `stall_hold_holds` releases it after `STALL_HOLD_CAP * FLOOR_CAP_MULT` (18000) plan steps or `FLOOR_BLACKOUTS` (10) blackouts while held (`tests/test_team_floor.py:99-109`). The plan's "never releases the hold" is therefore stronger than the code; report that gap, do not change it.

### 3.4 Unit tests for the module (`tests/test_training_ctl_exit.py`, same file)

Use `SimpleNamespace(step=..., __dict__={})`-style contexts like `tests/test_training_ctl_sustain.py` does. Required: (1) `publish_hold(ctx, 1)` sets `ctx.gym_hold_seen == (ctx.step, True)` (bool coercion) and `False` gives `(step, False)`; (2) `publish_floor` / `floor_unmet` round-trip and `floor_unmet` is False when never published; (3) `hold_clear`: stamped False and fresh -> True; stamped True -> False; never stamped -> False; stamped False but older than `fresh` -> False (boundary: exactly `fresh` steps old is still True); (4) `floor_hold` equals the OLD frontier expression for all four combinations of floor_unmet x stamped hold plus the "never stamped" case (write the old expression in the test as the oracle); (5) `test_old_writers_are_gone`: `inspect.getsource` of `plan_goal`, `training`, `goal_talk`, `frontier` contains no `gym_hold_seen =` assignment and no `__dict__["floor_unmet"]` / `.get("floor_unmet"` text; only `exit_rule.py` (and `adapters.py`, the shadow reader) may name them.

## 4. What NOT to do

- No ROM, no emulator process, no `runs/` access (absent in your worktree; do not look). Tests use `FakeEmulator` / `SimpleNamespace` / `tmp_path` only, via the helpers named above.
- **No timing or order change.** Every write stays at the exact line it was at, every read at the exact line it was at; do not hoist a `publish_*` earlier or later, do not compute a flag twice, do not cache. No behaviour change in part (a): if a test needs a decision to change, stop and report.
- Slice 5b is NOT yours: do not touch `GrindBudget`, `stall_hold_holds`, `STALL_HOLD_CAP`, the `gate_lifted` / `lifted_need` / `stall_hold` state (`plan_goal.py:135-149`, `:281-296`), `grind.py`, `grind_episode._end_reason`, `area_grind.py`. Do not delete `gym_hold_seen` or `floor_unmet` (they are still the flag names; only their writer and readers move). Do not touch `explorer/context.py` at all.
- Do not edit `training_ctl/{adapters,controller,state,sustain,target,roster}.py`, `explorer/behaviours/guards.py` (the loop guard), `knowledge/team_floor.py`, `explorer/planner*.py`.
- No lines added to `plan_goal.py` net, `explorer/memory.py`; no new log lines, no new `decisions.jsonl` rows, no new files in the run dir, no new dependency.
- Do not change the floor-release rule (`FLOOR_CAP_MULT`, `FLOOR_BLACKOUTS`) even though the plan text says "never releases": report the gap.

## 5. Verification (exact commands, from the worktree root)

Baseline first (Claude ran it on main, 2026-11-14, before #263): `103 passed, 1 warning in 4.65s`.
```
uv run pytest -q -p no:cacheprovider tests/test_grind.py tests/test_area_grind.py tests/test_grind_pressure_plan_goal.py tests/test_plan_goal_gym_road.py tests/test_goal_talk.py tests/test_training_v2_slice2.py tests/test_team_floor.py tests/test_training_ctl_shadow.py tests/test_training_ctl_sustain.py tests/test_training_ctl_target.py tests/test_frontier_patrol.py
```
Expected: 0 failed (with #263 merged the count is the same 103 plus the roster tests if you add `tests/test_training_ctl_roster.py` to the list; do that too, it must be 0 failed). If not, stop and write the failing ids; do not fix them.

After part (a), the same command must give the same 103 passed (plus nothing new yet). After part (b):
```
uv run pytest -q -p no:cacheprovider tests/test_training_ctl_exit.py
```
Expected: all pass, none skipped.
```
wc -l src/pokeagent/explorer/training_ctl/exit_rule.py src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py
git diff --stat origin/main
git grep -n "gym_hold_seen\|floor_unmet" -- src
```
Expected: `exit_rule.py` < 70; `plan_goal.py` <= 298 (it was 298); `context.py` exactly 300 and absent from the stat; the stat lists only `exit_rule.py`, `plan_goal.py`, `training.py`, `goal_talk.py`, `frontier.py`, the new test and the two adapted tests; the grep shows `gym_hold_seen` / `floor_unmet` ASSIGNED only in `exit_rule.py`, and otherwise only read in `adapters.py`, `state.py` (docstring/field names), `plan_goal.py` comments, `team_floor`-side text.

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`; about 3 minutes):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (main before #263 was `2951 passed, 63 skipped` on 2026-11-14; yours is that plus #263's tests plus your new ones; skip count unchanged).

**Not yours (the controller, on the laptop, after review):** the real-ROM proof that part (a) is a pure move. `decisions.jsonl` from a 12000-step seed 12 run and a seed 13 run from `heal_cerulean` must be BYTE-IDENTICAL to main (the same bar slice 3 met), and `tools/step_budget.py` rows unchanged; the shadow controller's `mismatches` stays empty. You cannot prove this; do not claim it. Your proof is the in-place, same-value diff plus the unchanged 103-test gate.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the worktree. Do not search, glob or hunt for missing things: if something named here is missing, stop and write why in the Status row. Never use `python -c`.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Never delete files. Create no scratch or debug files.
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/training-controller-slice5-exit-hold`; commit as you go (two commits as in section 3) and push the branch.
- No ROM, no `runs/` access.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with both commits and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `exit_rule.py` exists with `publish_hold`, `publish_floor`, `floor_unmet`, `hold_clear`, `floor_hold`, < 70 lines, no imports beyond `__future__`.
- [ ] `gym_hold_seen` and the floor flag are assigned only in `exit_rule.py`; every reader goes through it except the shadow `adapters.py`. <!-- test: tests/test_training_ctl_exit.py::test_old_writers_are_gone -->
- [ ] Part (a) is a pure move: the 103-test gate is unchanged and `plan_goal.py` net lines <= 0, `context.py` untouched.
- [ ] `floor_hold` equals the old frontier expression for every input. <!-- test: tests/test_training_ctl_exit.py::test_floor_hold_matches_the_old_frontier_expression -->
- [ ] The empty-ledger invariant is pinned. <!-- test: tests/test_training_ctl_exit.py::test_exit_floor_holds_with_empty_ledger -->
- [ ] No 5b file touched (`grind.py`, `grind_episode.py`, `area_grind.py`, the `gate_lifted` block).
- [ ] Baseline gate, new tests and the full suite: 0 failed.

## 8. Report

Findings first: `wc -l` of `exit_rule.py`, `plan_goal.py`, `context.py`; the `git grep` output; the per-file diff stat; any line number that differed from section 3 (the merged files win; report the difference); whether the empty-ledger test passed on first run; and the floor-cap gap noted in 3.3. Then the real output tails: baseline gate, after-part-(a) gate, new tests, the full-suite line. State plainly that no ROM was used and that the byte-identical seed 12/13 `decisions.jsonl` proof is the controller's, run on the laptop after review.

## Required from User

Nothing for the build. Queue only after #263 (slice 4) has merged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/training-controller-2026-11-13.md)
- Read(src/pokeagent/explorer/behaviours/plan_goal.py)
- Read(src/pokeagent/explorer/behaviours/goal_talk.py)
- Read(src/pokeagent/explorer/behaviours/frontier.py)
- Read(src/pokeagent/explorer/training.py)
- Read(src/pokeagent/explorer/grind.py)
- Read(tests/test_grind_pressure_plan_goal.py)
- Read(tests/test_training_ctl_sustain.py)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-training-controller-slice5-exit-h-30a7c4 |
| Base branch | - |
| Base commit | b46ff8c32ba3585bc5f8bb5561c23a8c07433ba6 |
| Head commit | d84aa46c744408ef65d85d35211f0bf1f702e01c |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-14 09:00 · robert-claude-laptop · none → Queued
- 2026-11-14 09:02 · robert-claude-laptop · Queued → Approved — lint override: The directive states all paths are under src/pokeagent/; training_ctl/__init__.py and training_ctl/adapters.py exist at src/pokeagent/explorer/training_ctl/. Reviewed by Claude (controller) 2026-11-14.
- 2026-11-14 09:13 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice5-exit-h-30a7c4; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7D6FSCSY278PQTX81JVY5FT
- 2026-11-14 09:18 · dispatcher · launched pid=12596; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice5-exit-h-30a7c4; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (12 declared need(s); 8 external))
- 2026-11-14 11:52 · agentflow-tick · In progress → Blocked — host shutdown/reboot; last activity 2026-11-14T09:21:46, found gone at 2026-11-14T11:43:15 (boot 2026-11-14T11:41:42, trigger lock-takeover); wip commit failed; wip/pokeagent-training-controller-slice5-exit-h-30a7c4@d84aa46 pushed
- 2026-11-14 12:20 · robert-claude-laptop · Blocked → Queued — Run lost to a clean laptop power-off at 09:24 (Event 1074, Start menu); no branch pushed. Requeue unchanged.
- 2026-11-14 12:22 · robert-claude-laptop · Queued → Approved — lint override: Same as the 09:02 override (re-approve after power-off lost the run): paths are src/pokeagent-relative; training_ctl/__init__.py and adapters.py re-verified present at src/pokeagent/explorer/training_ctl/.
- 2026-11-14 13:26 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice5-exit-h-30a7c4; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7DMYR1TMGEYPCH3S7K5EWX0
- 2026-11-14 13:32 · dispatcher · launched pid=21780; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice5-exit-h-30a7c4; not resynced: the reused worktree has uncommitted tracked changes; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (12 declared need(s); 8 external))
- 2026-11-14 13:38 · devin · In progress → Review — Slice 5a complete on the branch (commits ade8da3 + d84aa46, produced by the run lost to the 09:24 power-off; this run verified and pushed them). Findings: wc -l exit_rule.py=36 (<70), plan_goal.py=298 (net 0), context.py=300 (untouched). Line numbers matched section 3 exactly; no drift after #263. git grep: gym_hold_seen and floor_unmet are assigned only in exit_rule.py; raw reads remain only in adapters.py:18,23 (the shadow) and state.py field/comment; plan_goal.py:87,141 read via exit_rule.floor_unmet. Diff vs merge-base b20d4ce lists only the 8 expected files (the wider stat vs origin/main shows unrelated deletions: main advanced past our base with #272/#273 vision+goexplore merges). Empty-ledger invariant test PASSED on first run - it is a pin, not a fix. Floor-cap gap (report, not changed): stall_hold_holds releases the floor hold after STALL_HOLD_CAP*FLOOR_CAP_MULT (18000) plan steps or FLOOR_BLACKOUTS (10) blackouts while held - weaker than the plan's "never releases the hold"; noted for 5b/design, code untouched. Output tails: gate (12 listed files + test_training_ctl_roster.py + test_training_ctl_exit.py) = 129 passed, 0 failed; tests/test_training_ctl_exit.py alone = 6 passed, none skipped; full suite = 2990 passed, 63 skipped, 0 failed in 195s. Stray: previous run left tests/_sym_tmp.sym staged-but-uncommitted (7-line sym scratch); left untouched, not committed, not pushed. No ROM/emulator used; the byte-identical seed 12/13 decisions.jsonl proof is the controller's on the laptop after review. [origin] spent: devin 158 min est. n/a
<!-- queue:end -->
