# PokeAgent: Grind Points review fixes (PR #165) - no episode restart thrash, actions out of applies(), gate on center/proc/goto, logged fallbacks, lazy frames-per-step, measured xp used, a start() for callers

## Why this exists

PR #165 (branch `directive/pokeagent-grind-points-directive`, built from `docs/directives/Grind_Points_Directive.md`)
came back CHANGES-NEEDED with one blocker and seven should-fixes, quoted verbatim below. Ledger, choose, merge,
report and KNOWLEDGE.md passed (78 targeted tests). Since the review the coordinator merged main into the PR branch
(main has PR #164's frontier patrol fallback and PR #159's `trainee_check`; both were kept per the reviewer's notes).

**Branch rule for this run:** your run branch is created FROM the PR branch (the coordinator approves this row with
that base branch), so PR #165's files and the main merge are already in your worktree. Do NOT run `git merge`, `git
rebase` or `git stash` (the sandbox refuses them). Commit and push to your own run branch only; the coordinator
fast-forwards it onto PR #165's branch. Never push to main; never open a PR.

## The findings and what to do

1. **BLOCKER. "explorer/grind_episode.py update()/_end_reason(): an episode that ends restarts immediately, with no
   cooldown. For 'hurt with no potion' the sequence is: step N update() starts an episode (start checks no HP), step
   N+1 _end_reason says hurt, no potion, _finish(), step N+2 starts again... Each cycle records a 1-2 step, ~0 XP
   episode into the ledger (unique id run@step, never deduped), saves runs/grind_points.json, appends
   runs/legs/grind_drills.jsonl and rewrites mem.data['grind_points']. That drags the point's measured xp/min toward 0
   (MIN_MEASURED=2 is enough to override the prior in choose()), steers the agent off good points, and thrashes the
   disk every other step."** -> (a) Check every end condition at START too (hurt-with-no-potion, trainee ineligible,
   budget exhausted): an episode never starts in a state that would end it next step. (b) `EPISODE_COOLDOWN = 300`
   steps after any end (named, untuned) before another can start. (c) Episodes shorter than `MIN_EPISODE_STEPS = 50`
   or with zero battles are logged as `aborted` rows in `grind_drills.jsonl` but NOT folded into the ledger's measured
   mean. Tests: the restart loop from the review (hurt, no potion) produces exactly one aborted row and no ledger
   change; cooldown blocks a restart; a normal episode still folds.
2. **"update() runs inside GrindDrill.applies (side effects in applies: starts/finishes episodes, saves files). While
   under level and no point is chosen, every step runs _levels (read_party), trainee_slot_for and gp.choose, which
   BFS-es travel_steps per point per step."** -> `applies()` becomes a pure read of `grind_episode.active(ctx)` or the
   cheap under-level flag; the start/finish/save actions move into `step()` (or a tick hook); cache a "no point"
   answer for `NO_POINT_RECHECK = 200` steps. Test: `applies()` performs no file writes and no BFS (monkeypatch
   `travel_steps`/`choose` to count calls).
3. **"GrindDrill.applies (episode path) does not check ctx.center_intent, ctx.proc or ctx.goto. An episode can start
   while the agent is inside a Pokecenter on purpose (a buy or heal), routing it out."** -> Gate the start on
   `not ctx.center_intent and not ctx.goto and no active procedure` (find the procedure flag PR #162 uses); test it.
4. Boundary guard coverage: "behaviours that run after GrindDrill and can still walk off (Pickup, LearnerHunt,
   TeamHunt, TrainerHunt, ProcedureRunner, and the tail of GoalTalk) are not guarded, and OutsideSet only avoids
   warps (not edge connections to maps outside the set unless they are learned warps)." -> Guard the hunts
   (LearnerHunt, TeamHunt, TrainerHunt) with `grind_episode.active(ctx)` -> they do not apply during an episode; add
   edge connections to `OutsideSet` using the learned map connections (`mem.data["maps"][m]["warps"]` AND the
   outdoor edge transitions recorded in transitions, if the memory keeps them; if it does not, say so and document
   the limit in KNOWLEDGE.md). Test: a TeamHunt target outside the set is not pursued during an episode.
5. **Silent excepts (hard rule):** `grind_episode._levels` (`except Exception: return []`), `update()` trainee_slot
   (`except Exception: slot None`), `_ledger()` (`except (OSError, ValueError): pass` on the atlas seed),
   `measure._jsonl` (ValueError skipped), `points._points_of` (malformed skipped). -> Log once each via the module
   logger with the exception type/message; narrow the types where the callee is known.
6. **"grind/atlas.py:16 `FRAMES_PER_STEP = measure.frames_per_step_or_default()` runs at import time: it scans the
   cwd-relative runs/ directory (4,700+ run dirs on the live checkout) and reads up to 20 runs' transitions/levels on
   every process that imports grind.atlas, which now includes every explorer process and the test suite."** -> Make
   it lazy and cached (a function `frames_per_step()` with an `lru_cache`, called where the value is used), resolve
   `runs/` from the run root (the same root `explore_demo`/the swarm pass) not the cwd, and cap the scan to the 20
   most recent run dirs by name without stat-ing all 4,700 (sort the directory listing by name, which embeds the
   timestamp). Test: importing `grind.atlas` touches no filesystem (monkeypatch `Path.iterdir` to raise).
7. **"measure.xp_gained_in_episode (the MEASURED-from-levels.jsonl exp delta) is not used anywhere in production;
   _finish uses party_log.exp_total instead."** -> Use `xp_gained_in_episode` in `_finish` (both are RAM-read; the
   levels-based one is the directive's spec and is replayable from the run record), or delete it and document why
   `party_log.exp_total` is equivalent. Prefer using it.
8. **Cross-PR mismatch: "#166 (Team Management) calls `grind_episode.start(ctx)` via getattr; this PR provides
   update(), not start(), so #166's grind pressure silently falls back to train_route."** -> Add
   `grind_episode.start(ctx, reason: str) -> bool` as the explicit entry point (it applies the same start gates and
   cooldown and returns False with a logged reason when it cannot start); `update()` calls it. Test it.
9. `train_route.py` was rewritten (target/patch args, OutsideSet) and has no dedicated test: add
   `tests/test_train_route.py` covering the route-to-point step and `stay_on_route`'s set.

## What NOT to do

- Do not change the ledger schema, `choose()`'s scoring, the atlas formula, the report, or the swarm merge beyond
  what item 1(c) needs (aborted episodes excluded from the mean).
- Do not touch `planner*.py`, `ship_gate.py`, `team_value.py`, the segment store/scheduler, `frontier.py`'s patrol
  logic from #164 (only the `allowed` plumbing already merged).
- No new context fields (`explorer/context.py` 299); every explorer file under 300 (`points.py` is 298: split
  helpers into `grind/points_io.py` if it grows); no new dependency; no scratch files outside `.devin-scratch/`;
  never read outside the worktree (`runs/` is absent there: everything is fixture-tested, the controller measures).

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_grind_points.py tests/test_grind_measure.py tests/test_grind_episode.py tests/test_train_route.py tests/test_frontier_patrol.py tests/test_explorer_behaviours.py tests/test_grind.py tests/test_grind_atlas.py tests/test_area_grind.py tests/test_trainer_grind.py tests/test_team_hunt.py
```
Expected: all pass, plus your new tests.

```
uv run pytest -q
```
Expected tail: ~1908+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/grind/points.py src/pokeagent/grind/measure.py src/pokeagent/grind/atlas.py src/pokeagent/explorer/grind_episode.py src/pokeagent/explorer/behaviours/grind_drill.py src/pokeagent/explorer/behaviours/frontier.py src/pokeagent/explorer/train_route.py src/pokeagent/explorer/context.py
```
Expected: each under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory.
- Branch only (see the branch rule); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Items 1-9 applied with tests; suites green; sizes under 300; KNOWLEDGE.md notes the boundary limit if any.
- Status row set to Review with head sha, diff stat, wc -l line, test tails.

## Report

Head sha, diff stat, wc -l line, test tails, the constants chosen, and whether `OutsideSet` now covers edge
connections or only warps.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 21:40 · robert-claude-laptop · none → Queued — Review fixes for PR #165 (Sonnet: 1 blocker restart thrash + 8 should-fixes); approve with base_branch = the PR branch once the fixer's main merge is pushed
<!-- queue:end -->
