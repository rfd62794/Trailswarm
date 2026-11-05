# RL environment and evaluation gates

Read first: DIRECTION.md, tools/rl_env.py, tools/rl_train.py, src/pokeagent/telemetry.py, src/pokeagent/observations.py, src/pokeagent/qmodels.py, tests/test_rl_terminal.py, tests/test_rl_integration.py, tools/watch.py.

## Why this exists

This advances the reproducible bedroom-to-Boulder-Badge finish line by making actions and reported learning trustworthy. A saved battle model failed 3/3 greedy evaluations despite recording training wins. A controlled A-only test with hold=8 and settle=8 remained at the battle introduction for 350 actions before the timing fix; after the fix it wins in 101 actions. The current base now ticks hold+settle in SegmentEnv.step and versions observation semantics as 3. However FramePublisher.publish still advances one rendered emulator frame by default. It now accepts advance=False, but RL does not yet use that option. Observing a learner must not alter its trajectory. Evaluation currently runs only after training; that hides stalled policies.

Verified locally: uv run python --version reports Python 3.12.12. uv run pytest -q reports 164 passed, 1 skipped. ROM/checkpoint probes also verify win, escape and blackout; those local assets may not be present in a fresh worktree. Never fetch or hunt for them.

## Scope

In order: (1) frame-accurate/render-invariant RL controls and tests; (2) periodic evaluation in an independent environment; (3) minimal viewer/status integration for trustworthy learning metrics. Work primarily in the read-first files and focused tests. Reuse existing dependencies and model/schema helpers.

## The work

1. Preserve the hold+settle fix. Make RL publication use advance=False and schedule rendering within already-budgeted emulator ticks. Keep full-resolution display available. Publishing more/less often, attaching a viewer or enabling per-frame publishing must not add ticks or alter RAM transitions for identical actions. Preserve existing non-RL callers' behavior rather than silently changing campaign timing. Add counted-fake tests for held/released frames and render/publication invariance, plus a ROM-backed optional regression that proves repeated A can progress with default hold/settle when local assets exist.
2. Add independently configurable exploration decay duration instead of tying it to the total episode budget. Report epsilon. Add --eval-every and a small bounded --periodic-evals configuration. Evaluation must use its own environment, no learner registration/frame slot, no writes to training Q/visits/RNG, no checkpoint promotion, no reset of training progress. Use frozen policy snapshots and identical observation/action/reward configuration. Permit an explicit held-out start-state list; record source hashes and distinguish fixed-checkpoint regression from multi-state evaluation. A repeated deterministic checkpoint is not independent seed evidence. Preserve terminated/truncated bootstrapping and action masks in training targets and evaluation.
3. Emit atomic structured status fields for latest evaluation wins/attempts, mean solved steps, epsilon and evaluated model digest/version. Keep training outcomes and rewards separate. Add compact labels to tools/watch.py that tolerate old status records and distinguish TRAIN from EVAL. No invented success values when evaluation is absent.
4. Preserve schema/task isolation. Test that evaluation cannot contaminate live shared pools or mutate Q through defaultdict lookups. Reject incompatible checkpoints/models clearly. Do not automatically promote a first checkpoint or a new high episode reward to mastery. Keep raw outcome counters available.

## What NOT to do

Do not start/stop/reseat any live learner or viewer, edit runs/rl_agents.json, run controllers, touch existing runs files, alter live configurations or schedule work. The interactive controller owns rollout. Do not install packages, change Python pins, fetch a ROM, read outside the working directory or search for missing assets. Do not introduce PPO, a CNN, recurrence, new reward shaping, extra workers or a broad framework rewrite in this phase. Do not reduce the viewer resolution. Do not claim a learning improvement based only on passing tests or a scripted victory. Do not change main/master, push, merge or deploy. Do not modify unrelated comments or files.

## Verification

Run uv run python --version (expect 3.12.x), then uv run pytest -q (all available tests pass; local ROM tests may explicitly skip if assets are absent). Add targeted tests for tick counts, no extra ticks when publishing, evaluation state/RNG/table isolation, schedule parsing, action masks, terminal versus truncation and backward-compatible status rendering. Run uv run python tools/rl_train.py --help and git diff --check. Only run ROM probes if both roms/Pokemon Red.gb and baselines/battle.state already exist in this worktree; otherwise report that verification as not run, never search elsewhere. Do not run an unbounded training experiment.

## Rules for this run

NON-INTERACTIVE: a confirmation-requiring tool call is rejected and can end the run. No installs/downloads/fetches or reads outside this worktree. Use uv run, never bare Python. Work only on directive/rl-environment-and-evaluation-gates. No scratch/debug files; if unavoidable use .devin-scratch/ and leave it. Free models only if model configuration is touched (not expected). If genuinely blocked, stop and record the exact blocker in the queue Status row instead of trying alternative routes. Missing expected source files: stop and report; do not hunt. Never kill processes, clear shared-memory slots or edit the live registry. No push, merge, deployment, history rewrite or security-policy changes.

The Status row must not say Done merely because implementation ended. Report code/test completion and leave for independent review; if queue Review requires a push that this directive forbids, record the completion evidence without circumventing that restriction and ask the controller to publish/review. The controller performs outward-facing queue/branch transitions.

## Completion criteria

Frame publication adds zero simulation ticks in RL; same actions produce equal tick counts with/without rendering. Tests cover the release interval. Periodic greedy evaluation has an independent environment and leaves all training state unchanged. Status and viewer distinguish training from evaluation. All available tests pass; missing local assets are explicitly reported. Changes are committed on the directive branch and ready for controller review, not merged.

## Report

Findings first; then changed files, exact verification output tails, commit SHA, any unrun checks and remaining risks. State whether invariance was tested with a fake, the ROM, or both. State explicitly that no live seats or controllers were changed. Include any dependencies the next demonstration-assisted/shared-learner phase needs, but do not implement that next phase.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | repoman/rl-success-and-context |

**Status log**
- 2026-11-04 23:15 · devin-overseer (delegated) · none → Queued — Approved by Robert in this session; phase 1/2 of ordered RL recommendations. Base repoman/rl-success-and-context includes committed timing fix and directive.; under delegate.envelope
- 2026-11-04 23:15 · devin-overseer (delegated) · Queued → Approved — lint override: Lint checked main instead of the requested feature base. Verified with git ls-tree that observations.py, qmodels.py, both named tests and the directive are committed on repoman/rl-success-and-context. baselines/battle.state is deliberately an optional local-only asset; the directive explicitly requires skipping ROM checks when absent and forbids searching outside the worktree.; under delegate.band-normal, delegate.self-drafted, delegate.rate-limit
<!-- queue:end -->
