# PokeAgent: Team Management review fixes (PR #166) - the gym hold respects the lifted budget, release_pending has a lifecycle, stale catch_mode is reset, in-gym walks out, and the wiring is tested

## Why this exists

PR #166 (branch `directive/pokeagent-team-management-directive`, built from `docs/directives/Team_Management_Directive.md`)
came back CHANGES-NEEDED with two blockers and three should-fixes, quoted verbatim below. The pure logic and tests
passed (116 targeted). Since the review, the coordinator merged main into the PR branch (main has PR #163's catch
fix: `_attempt` keeps one `catch_attempt` per battle; the conflict was resolved as `ca = _attempt(...)` then
`if release_slot is not None: ca["release_slot"] = release_slot`).

**Branch rule for this run:** your run branch is created FROM the PR branch (the coordinator approves this row with
that base branch), so PR #166's files and the main merge are already in your worktree. Do NOT run `git merge`, `git
rebase` or `git stash` (the sandbox refuses them). Commit and push to your own run branch only; the coordinator
fast-forwards it onto PR #166's branch. Never push to main; never open a PR.

## The findings and what to do

1. **BLOCKER. "plan_goal.py ~134-141: the gym gate `if nv is not None and not nv.ready and gym is not None` ignores
   need/GrindBudget. `need` can be lifted to 0 by `_budgeted` (GRIND_BATTLES/STEPS/BLACKOUTS caps, the escape valve
   added after earlier stalls), but `nv.ready` stays False, so the agent can never enter the Brock/Misty gym again
   once budgeted: an infinite grind with no progress."** -> Skip the hold when the gate is lifted (need == 0 after
   `_budgeted`, or a budget-exhausted flag). Log one line when the hold is skipped because of the budget. Test: with
   the budget exhausted and `nv.ready` False, PlanGoal enters the gym; with budget available it holds.
2. **BLOCKER. "`release_pending` (catch.py:112, written to `team_plan.of(ctx)["release_pending"]`) is never cleared.
   `dialog.yesno_answer` then answers YES to ANY prompt containing 'deposit' or 'box' for the rest of the run
   (menu.py passes `bool(release_pending)`). A later 'Change BOX?'-style prompt gets YES."** -> Clear
   `release_pending` when the catch resolves (battle end, or the next battle starting) and match the exact deposit
   prompt text only (take the exact Gen 1 prompt wording from `docs/KNOWLEDGE.md` or the dialog rules; if it is not
   recorded, mark the matcher UNVERIFIED and match the narrowest phrase you can justify). Also be honest in the
   log/docs: in Gen 1 a full party sends the caught mon to the PC box automatically, so the policy mostly decides
   whether to THROW at all when every member is protected; say that in the KNOWLEDGE.md paragraph. Tests: lifecycle
   (set -> cleared on battle end; a later unrelated "box" prompt is answered NO).
3. **SHOULD-FIX. "catch.py: the party-full skip path `return None` (no release slot) happens before catch_mode/
   catch_hint are reset, so a stale catch_mode=True from an earlier battle can leave BattleMoves in weaken-only mode
   while Catch does nothing."** -> Reset `catch_mode = False`, `catch_hint = None` on that path; test it.
4. **SHOULD-FIX. "plan_goal._grind_step: when already inside the gym (m == gym) while not ready, `planned` is replaced
   by the grind step, which may be None (`train_route.step` from inside the gym), leaving Frontier to explore toward
   the leader; `_leader_avoid`'s block_sight is the only guard."** -> In the in-gym-and-not-ready case, route to the
   nearest non-gym map (reuse the existing walk machinery: `heal_walk`-style BFS over the learned graph, or
   `train_route`'s route to the grind map) before anything else; test with a synthetic ctx inside map 0x41 that the
   decision moves toward the exit.
5. **SHOULD-FIX. Missing tests:** the gym hold branch of `PlanGoal.step` (nv/gym/_enters), `_leader_avoid`,
   `switch_out._matchup_step` press flow with its MAX_PRESSES cap and the `matchup_switches` count on the battle
   record, and the `release_pending` lifecycle (item 2).
6. Docs: `trainers.GYM_BOSSES` covers only beat_brock and beat_misty, so the gate covers those two gyms; say so in
   KNOWLEDGE.md. `tools/grind_report.need_levels` now returns `(out, team_out)`; check its callers/tests.
7. Nits if cheap: cache `matchup_pick` per step (it runs `our_party` + best_move sims on every `SwitchOut.applies`
   in trainer battles); cache `full_party_slot` per battle at 6 members.

## What NOT to do

- Do not change `knowledge/team_plan.py`'s pure functions or their tests beyond what items 1-5 need.
- Do not touch `planner*.py`, `ship_gate.py`, `readiness.py` internals, `heal_walk.py`, `trainer_ledger.py`,
  `item_use.py` (PR #163's `catch_owns_bag` must keep holding; `tests/test_catch_bag_tug.py` unchanged and green).
- No new context fields (`explorer/context.py` 299, `memory.py` 299; state in `team_plan.of(ctx)`); every explorer
  file under 300 (`plan_goal.py` is 251, `switch_out.py` 196, `catch.py` 179: split before growing past 300).
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_team_plan.py tests/test_party_order_matchup.py tests/test_switch_matchup.py tests/test_grind_pressure_plan_goal.py tests/test_party_full_policy.py tests/test_catch_bag_tug.py tests/test_catch_seam.py tests/test_catch_policy.py tests/test_explorer_behaviours.py tests/test_team_readiness.py tests/test_team_value.py tests/test_catch_plan.py tests/test_team_hunt.py
```
Expected: all pass, plus your new tests.

```
uv run pytest -q
```
Expected tail: ~1908+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/behaviours/switch_out.py src/pokeagent/explorer/behaviours/catch.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
```
Expected: each under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory.
- Branch only (see the branch rule); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Items 1-5 applied with tests; suites green; sizes under 300; KNOWLEDGE.md updated per item 2 and 6.
- Status row set to Review with head sha, diff stat, wc -l line, test tails.

## Report

Head sha, diff stat, wc -l line, test tails, the exact deposit prompt you matched and whether it is verified.
