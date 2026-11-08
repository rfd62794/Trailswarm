# PokeAgent: Goal Procedures review fixes (PR #162) - trainer-only AfterVictory, a real heal via heal_walk, no new context fields, one beaten-trainers source, logged fallbacks, no hard-coded rival tile

## Why this exists

PR #162 (branch `directive/pokeagent-goal-procedures-directive`, head 1137692, built from
`docs/directives/Goal_Procedures_Directive.md`) came back CHANGES-NEEDED with six should-fix findings, quoted below.
Since the review, main gained PR #158 (trainer ledger: `src/pokeagent/explorer/trainer_ledger.py`,
`trainer_hooks.py`, `trainer_route.py`; `explorer/context.py` is now 299 lines) and PR #159 (status care:
`src/pokeagent/explorer/heal_walk.py` with `heal_walk.start(ctx, ...)`, a real walk to the nearest Pokecenter that
survives PlanGoal; `explorer/status_care.py` keeps its state in `status_care.of(ctx)` on `ctx.__dict__` so it adds no
context fields). Those are the two pieces this PR must now use.

**Branch rule for this run:** your run branch is created FROM PR #162's branch `directive/pokeagent-goal-procedures-directive` (the coordinator approves this row with that base branch and resolves any conflict with main beforehand), so PR #162's files are already in your worktree. Do NOT run `git merge`, `git rebase` or `git stash` (the sandbox refuses them). Commit and push to your own run branch only; the coordinator merges it back into PR #162's branch. Never push to main; never open a PR.

## The findings and what to do

1. **"`AfterVictory` fires on every battle win, not only trainer wins."** `after_victory.py` applies when
   `ctx.battles_won > after_victory_seen`, and `battles_won` counts wild wins too; the directive says one decision per
   TRAINER win. -> Gate on the trainer result: the battle record `kind == 2`, or `ctx.trainer_npc` beaten. Wild wins
   must not trigger a decision, a `walk_to_center` search, a log line, or a `runs/after_victory.jsonl` row. Test both.
2. **"The `heal` decision has no effect on the road."** `AfterVictory` sets `ctx.center_intent = "heal"`, which
   `plan_goal.py:34-35` clears outside a Pokecenter, so nothing walks; `ProcedureRunner._paused` then waits up to
   `HEAL_PAUSE_MAX = 600` steps for `party_full`. -> Call `heal_walk.start(ctx, reason="after_victory")` (PR #159)
   from the `heal` branch instead of setting `center_intent`; the runner's pause ends when the walk ends (healed or
   abandoned) rather than on a fixed 600 steps. Read `heal_walk.py` and `behaviours/status_care.py` for the request
   shape and who executes the walk (StatusCare runs before PlanGoal; make sure Procedures/AfterVictory do not fight
   it: when a heal walk is pending, the runner is paused). Test: a trainer win with low HP starts a heal walk request;
   the runner is paused while the request exists and resumes when it is cleared.
3. **"Size headroom."** #162 adds four `context.py` fields (300 lines at the review; main is now 299, so the merge
   lands at 303 and `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size` fails). -> Move the
   four fields into a state dict on `ctx.__dict__` exactly as `status_care.of(ctx)` does (a small `procedures/state.py`
   with `of(ctx) -> dict`), so `context.py` stays at main's 299 or lower.
4. **"Two `beaten_trainers` implementations."** `procedures.predicates.beaten_trainers` reads NPC entries plus a
   cwd-relative `runs/battles.jsonl`; PR #158's `trainer_ledger.beaten_trainers` (via `trainer_hooks`) matches ROM
   placements and is the intended source. -> Delegate to the #158 function; resolve any `runs/` path from the run
   directory (`ctx.run_dir` or the equivalent the engine exposes), never the cwd; `after_victory.LOG_PATH` likewise.
   Remove the duplicate. Test that a walked-up trainer (position off by one tile) still counts as beaten.
5. **"Silent except."** `after_victory.py:61` `except Exception: walk = None` with no log. -> Log once per distinct
   message via the module logger; narrow the type if the callee tells you.
6. **"Hard-coded rival coordinates in the seed."** `procedures/seeds.py` `RIVAL_AT = [96, 36, 4]` comes from the
   suspect RIVAL1 row and is used as the `fight_trainer` target tile; the directive said not to seed from that row
   and not to hard-code corridor coordinates. -> Use a null target resolved at run time (the runner finds the rival
   by the trainer ledger's placement for that map, or by the battle event), or the boss party only. Regenerate the
   committed seed JSON with the test-covered `seed_ss_anne` helper; the test must assert no literal coordinates
   remain in the seed for the rival step.

## What NOT to do

- Do not change the procedure data format beyond what finding 6 needs; do not touch `planner*.py`, `ship_gate.py`,
  `heal_walk.py` internals, `trainer_ledger.py` internals (import and call them), or the registry order the directive
  fixed (AfterVictory right after BattleMoves; ProcedureRunner right before Frontier).
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree; if a named file is
  missing, stop and say so in the Status row.
- Every file under `src/pokeagent/explorer/` stays under 300 lines; `context.py` must not grow.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_procedures.py tests/test_procedures_mine.py tests/test_after_victory.py tests/test_procedure_runner.py tests/test_explorer_behaviours.py tests/test_status_care_behaviour.py tests/test_trainer_glue.py
```
Expected: all pass (adjust to the files that exist; `ls tests/test_proc* tests/test_after*`).

```
uv run pytest -q
```
Expected tail: ~1905+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/explorer/context.py src/pokeagent/explorer/behaviours/after_victory.py src/pokeagent/explorer/procedures/*.py
```
Expected: context.py <= 299; every file under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory.
- Branch only (see the branch rule); commit as you go; never commit to or push main; never merge to main.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Findings 1-6 applied with tests; `context.py` unchanged from main; suites green; sizes under 300.
- Status row set to Review with head sha, diff stat, wc -l line, test tails.

## Report

Head sha, diff stat, wc -l line, targeted and full-suite tails, the conflicts you resolved in the merge, anything
you could not do.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | directive/pokeagent-goal-procedures-review-fixes-directive |
| Base branch | directive/pokeagent-goal-procedures-directive |
| Base commit | c04c8c9f091022bba1911d981183d8941a650c6d |

**Status log**
- 2026-11-07 20:37 · robert-claude-laptop · none → Queued — Review fixes for PR #162 (Sonnet CHANGES-NEEDED, six should-fixes); uses heal_walk (#159) and trainer_ledger (#158); branch merges PR #162's branch first
- 2026-11-07 20:42 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; review fixes for PR #162 which Robert wants merged
- 2026-11-07 20:42 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-goal-procedures-review-fixes-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6WD4C03TZ3VQYAWZX5JK8AZ
- 2026-11-07 20:49 · dispatcher · launched pid=26948; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-goal-procedures-review-fixes-directive; provisioned: uv sync --frozen
- 2026-11-07 20:50 · devin · In progress → Blocked — git merge origin/directive/pokeagent-goal-procedures-directive refused by the run's permissions (git merge/rebase/stash are refused); branch is still plain main a69a759 and none of PR #162's files (procedures/, behaviours/after_victory.py) exist to fix. Run needs merge permission for this step or a dispatcher-side pre-merge.
- 2026-11-07 20:57 · robert-claude-laptop · Blocked → Queued — Requeue: PR #162's branch now has main merged (d8e701b, context fields moved to procedures/state.py = finding 3 done); run starts FROM that branch (approve with base_branch) since the sandbox refuses git merge
- 2026-11-07 20:57 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; requeued with the PR branch (main already merged in) as base because the sandbox refuses git merge
<!-- queue:end -->
