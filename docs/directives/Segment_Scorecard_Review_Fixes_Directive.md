# PokeAgent: Segment Scorecard review fixes (PR #161) - module sizes, logged fallbacks, read-only review CLI, split/rejoin flap guard, partial-window means

## Why this exists

PR #161 (branch `directive/pokeagent-segment-scorecard-directive`, head 9abf2b1, built from
`docs/directives/Segment_Scorecard_Directive.md`) is green on the verify lane (1905 passed, 0 failed at 9abf2b1 onto
main 078e8f3) and passed review on correctness, but came back CHANGES-NEEDED on five should-fix findings, quoted
verbatim below. This directive applies them so the PR can merge.

**Branch rule for this run:** your run branch is created FROM PR #161's branch `directive/pokeagent-segment-scorecard-directive` (the coordinator approves this row with that base branch and resolves any conflict with main beforehand), so PR #161's files are already in your worktree. Do NOT run `git merge`, `git rebase` or `git stash` (the sandbox refuses them). Commit and push to your own run branch only; the coordinator merges it back into PR #161's branch. Never push to main; never open a PR.

## The findings and what to do

1. **Size ceiling.** "The directive says each new module must be under 300 lines. `src/pokeagent/segment_grades.py`
   is 323 lines. Existing `tools/seg_sched.py` grew from 258 to 410 lines." -> Move `segment_par`,
   `entries_exits_for`, `par_for_best` (and their private helpers) from `segment_grades.py` into a new
   `src/pokeagent/segment_par.py`; re-export from `segment_grades` so every existing import path still works. Split
   `tools/seg_sched.py`: the scorecard/grade steering it gained goes to `tools/seg_sched_grades.py` (pure functions)
   and `seg_sched.py` calls them. Every touched module under 300 lines (`wc -l`).
2. **Silent excepts.** "`segment_grades.grade_all` swallows a par error silently (`except Exception: par = None`).
   `start_grade` returns 'n/a' silently. `seg_sched._par` sets `_grids = None` silently. `review/segments._grids` is
   silent too." -> Keep the fallback behaviour; log once per distinct message through the module logger
   (`logging.getLogger(__name__)`, WARNING, exception type + message; a module-level `set` of seen messages so a
   frequent caller does not spam). Narrow `except Exception` to the types the callee raises where you can tell
   (OSError, ValueError, KeyError); where the callee is opaque keep `Exception` with a one-line comment saying why.
3. **`review segments` mutates `runs/segments.json`.** "`review/segments.py` calls `seg_ingest.ingest` plus `ss.save`
   by default, with no store lock/txn, while a supervisor's `Curriculum.txn` may be writing the same file." -> Make
   `--no-ingest` the default for `pokeagent review segments` (a review tool must not write); add `--ingest` as the
   opt-in; when ingesting, take the same store lock/transaction the curriculum uses (`Curriculum.txn` or the store's
   lock helper; find it in `tools/segments.py` / the segment store module). Update help text and the tests that
   assumed ingest-by-default.
4. **Split and rejoin can flap.** "After `should_rejoin` calls `seg_split.reset`, `split_retry_at` is popped. The next
   `maybe_split` can immediately re-split via `should_split_long`, because the parent's window median may still
   exceed 3 times par." -> On rejoin set `split_retry_at = n + WINDOW` (the WINDOW the window median uses). Test:
   rejoin followed immediately by `maybe_split` does not split; after WINDOW more attempts it may.
5. **`_mean_flag` is all-or-nothing.** "A window mixing old attempts (no field) and new ones gives `None` for the
   blackout, stall and loop rates, even though most attempts carry the field." -> Mean over the attempts that carry
   the field; None only when none do. Test with a mixed window.

Optional if cheap: `groups()` recomputes grades twice per `next_job` (cache per call).

## What NOT to do

- Do not change grade definitions, share bounds (polish 0.05-0.35), chain-best semantics, or `runs/segment_sets.json`
  defaults. Nothing steers on the blackout column yet; leave that.
- Do not touch `src/pokeagent/explorer/`, `planner*.py`, `ship_gate.py`.
- No new dependency. No scratch files outside `.devin-scratch/`. Never read outside the worktree; if a named file is
  missing, stop and say so in the Status row.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
ls tests/test_seg* tests/test_review_seg* tests/test_segment*
uv run pytest -q tests/test_segment_grades.py tests/test_segment_provenance.py tests/test_segment_curriculum.py tests/test_segment_determinism.py tests/test_explorer_behaviours.py
```
plus every other file the `ls` lists. Expected: all pass, including your new tests.

```
uv run pytest -q
```
Expected tail: ~1905+ passed, 40 skipped (ROM-gated), 0 failed. If 36 `test_review_*` tests fail you have not
merged main (the fixtures landed in PR #156).

```
wc -l src/pokeagent/segment_grades.py src/pokeagent/segment_par.py tools/seg_sched.py tools/seg_sched_grades.py src/pokeagent/review/segments.py
```
Expected: each under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory.
- Branch only (see the branch rule above); commit as you go; never commit to or push main; never merge to main.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Findings 1-5 applied with tests; sizes under 300; suites green.
- Status row set to Review with the head sha, diff stat, wc -l line, and test tails.

## Report

Head sha, diff stat, wc -l line, targeted and full-suite tails, anything you could not do.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-segment-scorecard-review-fixes-directive |
| Base branch | directive/pokeagent-segment-scorecard-directive |
| Base commit | e7bcdc8bd88132783cdf1e3cc9193f58addf1806 |
| Head commit | c6f38d44fdabfa6724a4b7afd812725bc7cc6583 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 20:37 · robert-claude-laptop · none → Queued — Review fixes for PR #161 (Sonnet CHANGES-NEEDED, five should-fixes); branch merges PR #161's branch first
- 2026-11-07 20:40 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; review fixes for PR #161 which Robert wants merged
- 2026-11-07 20:40 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-segment-scorecard-review-fixes-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6WD0KXKRYTTZ88XQ2FR7WM0
- 2026-11-07 20:47 · dispatcher · launched pid=24544; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-segment-scorecard-review-fixes-directive; provisioned: uv sync --frozen
- 2026-11-07 20:49 · devin · In progress → Blocked — Refused required command: git merge origin/directive/pokeagent-segment-scorecard-directive (git merge is refused-on-purpose in this sandbox; all merge-equivalents are too). The directive's branch rule requires it as step one: PR #161 head 9abf2b1 is not an ancestor of HEAD and its files (e.g. src/pokeagent/segment_grades.py) are absent, so the five review fixes cannot be applied. Fix: merge PR #161's branch into directive/pokeagent-segment-scorecard-review-fixes-directive before dispatch, or allow git merge for this run, then requeue.
- 2026-11-07 20:52 · robert-claude-laptop · Blocked → Queued — Requeue: the run needed git merge, which the sandbox refuses; directive rewritten so the run branch starts FROM PR #161's branch (approve with base_branch)
- 2026-11-07 20:52 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; requeued with the PR branch as base because the sandbox refuses git merge
- 2026-11-07 20:53 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-segment-scorecard-review-fixes-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6WDR6413WC7980KAPXQ74BW
- 2026-11-07 20:58 · dispatcher · launched pid=13744; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-segment-scorecard-review-fixes-directive; resynced: merged directive/pokeagent-segment-scorecard-directive into directive/pokeagent-segment-scorecard-review-fixes-directive (1 commit(s), clean); provisioned: uv sync --frozen
- 2026-11-07 21:13 · devin · In progress → Review — All 5 findings applied + optional groups() cache. Head c6f38d4 (pushed). DIFF: 10 files, +463/-275. wc -l: segment_grades.py 257, segment_par.py 83 (new: segment_par/entries_exits_for/par_for_best/make_par_fn, re-exported), seg_sched.py 283, seg_sched_grades.py 213 (new pure fns: grade_groups/frontier_seg/choose/pick/live_holds/rejoin_goals/rejoin_candidates/pending_confirm/pending_broken_replay/pending_repro/resolve_suite/log_refusals), review/segments.py 118. FINDINGS: (1) par code -> segment_par.py; sched steering -> seg_sched_grades.py; all touched <300. (2) log-once WARNING via module logger + seen-set in grade_all par_fn, start_grade, seg_sched._par, review _grids; opaque callees keep Exception + comment. (3) `pokeagent review segments` now read-only by default; --ingest opt-in runs ingest inside ss.locked (same txn as Curriculum.txn); tests updated + new read-only/opt-in test. (4) seg_split.reset sets split_retry_at = n + WINDOW (flap guard). (5) _mean_flag means over attempts carrying the field; None only when none do. Optional: next_job caches _gm into choose() and uses ssg.frontier_seg (one grade_all per call, was 3). TESTS: new test_par_fn_failure_is_logged_once, test_event_rates_mean_over_attempts_carrying_the_field, test_rejoin_does_not_flap_straight_back_to_a_split, test_default_is_read_only_and_ingest_is_opt_in. TARGETED (11 files incl. curriculum_hold): 140 passed, 1 skipped. FULL SUITE: 1909 passed, 40 skipped, 0 failed in 201.62s. [origin] spent: devin 16 min est. n/a
- 2026-11-07 21:41 · robert-claude-laptop · Review → Done — note: Its branch tip c6f38d4 was fast-forwarded onto PR #161's branch and merged to main with PR #161 (merge commit); Haiku delta APPROVE; green verify at c6f38d4.
<!-- queue:end -->
