# Marathon Watch follow-up: XP resets the grind clock only toward the floor

Repo: PokeAgent (this worktree). Branch: directive/pokeagent-marathon-watch-xp-floor (never commit to main, never push, never merge).
Base: origin/main. Build it in your worktree only.

## Why this exists
The independent review of PR #321 found that rules.rule_map_dwell and rules.rule_goal_budget restart their clocks from view.train_at, and src/pokeagent/marathon/reader.py (about line 118, in RunView.refresh) sets train_at on ANY levels.jsonl XP or level gain (tp.gained). The level floor is never checked. The original marathon directive said: XP resets only the grind clock and only toward the floor.

Failure: after the S.S. Anne, if the first pending goal is in GRIND_GOALS, a detour with an XP trickle while the floor is already met (today's stall 4, the Route 24 detour) gets the 6000-press grind budget and a clock reset on every XP gain, so it never flags. A 17k-press gym patrol with occasional XP can escape the same way.

## Read first (all inside this worktree)
- src/pokeagent/marathon/reader.py (RunView.refresh, train_at, current_goal, pending_goals)
- src/pokeagent/marathon/rules.py (rule_map_dwell, rule_goal_budget, GRIND_GOALS)
- tests/test_marathon_rules.py, tests/test_marathon_bundle.py, tests/test_marathon_watch.py (helpers make_run, presses, goals, ladder_upto, level_gain)
- docs/directives/PokeAgent_Marathon_Watch_Directive.md (the original spec)
- src/pokeagent/knowledge/team_floor.py (FLOOR_BY_GOAL, TEAM_FLOOR_MEMBERS, Floor.check semantics)
- src/pokeagent/explorer/training.py (TRAIN_LEVEL_BY_GOAL, the fallback table)
- src/pokeagent/training_progress.py (marks, gained; levels.jsonl party rows are [species, level, exp, hp, max_hp])

## Scope (exact files)
- Edit: src/pokeagent/marathon/reader.py
- Add if reader.py would pass ~150 lines: one small new module src/pokeagent/marathon/floor.py (pure functions, one job)
- Edit: tests/test_marathon_rules.py (new cases); touch the other tests/test_marathon_*.py files only if an existing assertion must change
- rules.py only if a docstring or a tiny signature change is needed

## The work
1. Define the floor for the current pending goal (view.current_goal) from the repo's own sources: FLOOR_BY_GOAL first, else TRAIN_LEVEL_BY_GOAL as the level. Members required = TEAM_FLOOR_MEMBERS. Import these; never copy numbers.
2. levels.jsonl rows carry no move data, so the sendable test in team_floor.check cannot run here. Use the party rows only: count members at or above the floor level, excluding Magikarp (find its species id in the repo's existing tables; if no id is reachable cheaply, say so in the Status row and count all members). Cap the required count at the party size.
3. train_at advances on a gain only when it moves the team toward the floor, judged against the floor of the goal pending at that row:
   - the count of members at or above the floor increased, or
   - the floor is unmet and the best under-floor member's level rose.
   Once the floor is met, XP never advances train_at. A goal that has no floor from either table advances train_at as today (documented in a comment, and listed in your Report).
4. The pending goal can change as goal_frames.jsonl is read. Evaluate each levels row against the pending goal as of that row's step (read goal_frames before levels, as refresh already does), and keep the previous party marks so a goal change never counts as a gain.
5. rules.py keeps reading view.train_at unchanged; the fix lives where train_at is set.
6. Tests (synthetic run dirs, extend the existing helpers; give level_gain a multi-member party form):
   - XP trickle with the floor already met, first pending goal in GRIND_GOALS: still flags goal_budget and map_dwell.
   - XP toward an unmet floor (a member rising, or a second member reaching the floor): resets the grind clock, status ok inside the budget.
   - Floor reached part-way: gains before it reset the clock, gains after it do not, and the run flags once the budget since the last reset passes.
   - The existing healthy-grind case (case 6 of the original directive) still passes, with its party below the floor.

## What NOT to do
- No changes outside src/pokeagent/marathon/ and tests/test_marathon_*.py, except a tiny read-only helper in an existing module if the floor lookup truly needs one (say so in the Report).
- No ROM, no emulator, no GUI, no web views, no process started or stopped.
- Do not change thresholds, rule order, bundle format, or the CLI.
- Do not edit team_floor.py, training.py, or training_progress.py behaviour.

## Verification
Only these two commands, in this order:
- `uv run pytest -q -p no:cacheprovider -rfEs tests/test_marathon_rules.py tests/test_marathon_bundle.py tests/test_marathon_watch.py`
- `uv run pytest -q -p no:cacheprovider -rfEs`
Zero failures or it is not done. Run nothing else (no tools scripts, no help flags, no other commands).

## Rules for this run
- NON-INTERACTIVE. No installs, no fetches, no network.
- Never read outside the worktree. No scratch files except under .devin-scratch/.
- Do not hunt for missing files or symbols. If something named here is absent or differs, stop and write why in the Status row.
- SOLID/SRP/KISS: small modules, one job each.
- Branch directive/pokeagent-marathon-watch-xp-floor; never commit to main, never push, never merge.

## Forbidden Actions
- Reading or editing the main checkout, live runs data, ROMs, saves, or anything outside the worktree.
- Starting, stopping, or signalling any emulator, agent, or swarm process.
- Touching protected repos (TeleseroAdminSuite2026, DialerListPulse).
- Committing to main, pushing, merging, force-push, history rewrite, marking the directive Done.
- Installs, lockfile or dependency edits.

## Required from User
None expected.

## Completion criteria
- train_at advances only on floor-directed gains; the new tests above pass; the full serial suite shows 0 failed.
- Existing marathon tests pass unchanged except any assertion the fix legitimately changes (list each in the Report).

## Report
Findings first: the floor source used per goal, how Magikarp was handled, which goals had no floor and fell back to the old behaviour. Then evidence: the tails of both pytest runs. Then files changed and any rule or case you could not implement and why.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-16 07:24 · robert-claude-laptop · none → Queued
<!-- queue:end -->
