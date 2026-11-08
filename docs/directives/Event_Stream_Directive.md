# PokeAgent: one event stream per run - a single typed, buffered events.jsonl replaces the per-run jsonl files, with one reader that every tool uses

## Why this exists

Robert 2026-11-07 approved: "One event stream per run. Runs write six or more files; fold them into one append-only
event stream with typed rows; the review tools, viewer, segment scorecard, and swarm merge all read from it. Fewer
writes, one schema, and the review tooling stops joining files by step number by hand." Follows
`Perf_Baseline_Directive.md` (buffered jsonl writer) and `Agent_Footprint_Directive.md`; do not start before both
have merged.

Measured 2026-11-07 (inventory on main; finished run runs/explore-20261107-191457-26240, 60,000 steps):

| file | writer (file:line) | rows / 1k steps | readers (count) |
|---|---|---|---|
| transitions.jsonl | `tools/explore_demo.py:114` opens; `explorer/press.py:121` write_transition | ~1,000 | 18 modules (atlas/agents_io, explorer/context, legs/split, novelty/backfill, ramlab/headless, review/load, review/loops, review/swarm, stalls, tools/atlas, backtrack_report, leg_report, make_world_gif, overnight, review_runs, rl_curriculum, golden_trace, explore_headless) |
| decisions.jsonl | `explorer/decisions.py:46-55` DecisionLog | ~984 | 13 modules + 4 tests |
| levels.jsonl | `explorer/party_log.py:159` | ~1.9 | review/events, review/load, training_progress, tools/swarm_watch |
| goal_frames.jsonl | `explorer/press_goals.py:59`, `press_stop.py:37` | ~0.4 | 8 modules |
| progress.jsonl | `explorer/progress.py:70` (engine.py:127) | ~71 | stalls.py:181 |
| loops.jsonl | `explorer/loop_veto.py:48` | ~24 | stalls.py:180, context.py:256, loop_memory.py |
| status_care.jsonl | `explorer/status_care.py:193` | rare | writer only + tests |
| after_victory.jsonl | NO writer in src/tools | 0 | review/load.py:81,115, review/events.py (dead readers) |
| trainers.json | `trainer_hooks.py:163,203,227` | 1 doc | trainer_hooks, trainer_ledger |
| meta.json, novelty_delta.json | explore_demo/press_goals/trainee/economy; novelty/tracker | 1 doc each | many |
| runs/battles.jsonl (shared) | `behaviours/battle.py:270` | 17,111 rows, 15.7 MB | 10 modules |

Row schemas (real rows): transitions {step, from, button, to, moved, textbox, text, facing, source, optional
ahead_tiles, stand_tile, battle_flag, battle_turn, sprites, ram_diff, item, event_flags, trigger}; decisions {step,
behaviour, rule, button, map, x, y, goal_stage, box, battle, outcome, reversal} plus event rows; levels {step, frame,
map, cause, party[[species, level, exp, hp, max_hp]], optional level_ups, evolved, moves_learned}; goal_frames {goal,
step, frame}; progress {step, frame, reasons, since}; loops {step, map, x, y, facing, text, battle, button, rule,
behaviour, no_progress, veto_until, source, kind}; status_care {step, map, provenance, event, ...}.

The review tools (`src/pokeagent/review/load.py`) already join these by step. `tests/fixtures/review/runs/` (PR #156)
holds hand-written fixtures in the OLD multi-file layout and the review tests depend on them.

Read first: `src/pokeagent/review/load.py` and `review/events.py` (the de facto reader), `explorer/decisions.py`,
`press.py:100-145`, `party_log.py`, `press_goals.py`, `progress.py`, `loop_veto.py`, `status_care.py:180-200`,
`tools/swarm_merge.py` (what it reads from run dirs), `tools/segments.py` / `seg_ingest.py` (goal_frames readers),
Perf_Baseline's buffered writer.

## Scope (in this order)

1. `src/pokeagent/events.py` (new, pure, under 250 lines): the stream schema and the one writer.
2. `src/pokeagent/review/stream.py` (new, under 250 lines): the one reader with per-kind views and a legacy fallback.
3. Switch the writers; keep every legacy reader working through the reader; delete dead readers.
4. Fixtures: add an events-stream fixture run beside the legacy ones; tests for both layouts.
5. KNOWLEDGE.md schema paragraph; `pokeagent review` unchanged in output.

## The work

### 1. The stream

- `events.jsonl` in the run dir, one JSON object per line, every row carrying `k` (kind), `s` (step) and `f`
  (frame when known). Kinds: `tr` (transition: the transitions row minus step), `de` (decision), `lv` (levels), `go`
  (goal), `pr` (progress), `lp` (loop), `sc` (status_care), `av` (after_victory, when a writer exists), `ev` (the
  decisions.py event rows), `meta` (one row at start with the meta.json content; meta.json itself stays for the many
  readers that stat it). Field names inside a row are the EXISTING names (no renames), so readers map 1:1.
- `EventWriter(run_dir)`: the single buffered appender (reuse Perf_Baseline's buffer: flush every 50 rows or 5 s, and
  on exit/`os._exit` paths via the same hook); `write(kind, step, frame=None, **row)`; a `schema_version: 1` field in
  the `meta` row.
- Keep `runs/battles.jsonl` and `xp_estimates.jsonl` (shared, cross-run) as they are; keep `trainers.json`,
  `novelty_delta.json`, `meta.json` (single documents) as they are.

### 2. The reader

- `review/stream.py`: `load_events(run_dir) -> iterator of rows`; `rows(run_dir, kind)`; `transitions(run_dir)`,
  `decisions(run_dir)`, `levels(run_dir)`, `goals(run_dir)`, `progress(run_dir)`, `loops(run_dir)`, `status_care(run_dir)`
  returning lists of dicts in the LEGACY shape (with `step` restored) so existing code can switch by import only.
- Legacy fallback: when `events.jsonl` is absent, each view reads the corresponding legacy file. When both exist, the
  stream wins and a one-time log line says so.
- `review/load.py` and `review/events.py` are rewritten to call `stream`; their public functions keep their names and
  return shapes.

### 3. Writers and readers

- Switch the writers listed in the table to `EventWriter` (press.py, decisions.py, party_log.py, press_goals.py,
  press_stop.py, progress.py, loop_veto.py, status_care.py). Remove the per-file opens (`explore_demo.py:114`,
  `engine.py:127`, `explore_demo.py:142`).
- Switch every reader in the table to `review.stream` views (18 + 13 + ... modules; do them all; grep is the list).
  `explorer/context.py:256` and `loop_memory.py` read loops during the run: give them the same view over the live
  buffered file (flush before read, or read the writer's in-memory tail; choose the simpler and say which).
- `after_victory.jsonl`: no writer exists; PR #162 (Goal Procedures) adds one (`after_victory.LOG_PATH`). Coordinate:
  the `av` kind is defined here; #162's follow-up switches its writer when it lands. Remove nothing from #162.
- Delete the dead code paths that only existed to open the per-file handles.

### 4. Fixtures and tests

- Add `tests/fixtures/review/runs/<one synthetic run>-stream/` with `events.jsonl` equivalent to one existing legacy
  fixture run; the review tests run against both layouts and assert identical output (`pokeagent review run` text
  and `--json`).
- `tests/test_events_writer.py` (buffer, flush on count/time/exit, schema_version, kinds), `tests/test_review_stream.py`
  (views, legacy fallback, stream-wins rule), and an end-to-end test that a synthetic engine step writes `tr` + `de`
  rows through the real seams.

### 5. Docs

- `docs/KNOWLEDGE.md`: "Run event stream" section: the file, the kinds, the row fields per kind, the fallback rule,
  and the note that `runs/` from before this change stay readable.

## What NOT to do

- Do not rename row fields or change their values; do not drop any field a reader uses.
- Do not change `runs/battles.jsonl`, `xp_estimates.jsonl`, `maps.json`, `trainers.json`, `meta.json`,
  `novelty_delta.json`.
- Do not change review output (text or JSON) for the legacy fixtures: that is the regression test.
- Do not touch behaviours' decisions, `planner*.py`, `ship_gate.py`; keep `explorer/context.py` and `memory.py`
  under 300 (no new fields).
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_events_writer.py tests/test_review_stream.py tests/test_review_run.py tests/test_review_swarm.py tests/test_review_replay.py tests/test_review_diff.py tests/test_cli_review.py tests/test_review_noise.py tests/test_explorer_behaviours.py tests/test_stalls*.py tests/test_loop_veto_engine.py
```
Expected: all pass (list extra files with `ls tests/test_review* tests/test_stall*`).

```
uv run pytest -q
```
Expected tail: ~1908+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/events.py src/pokeagent/review/stream.py src/pokeagent/review/load.py src/pokeagent/review/events.py src/pokeagent/explorer/press.py src/pokeagent/explorer/decisions.py
```
Expected: each under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory.
- Branch only; commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Every per-step writer goes through `EventWriter`; every reader goes through `review.stream`; legacy run dirs still
  read; review output identical on legacy fixtures; the stream fixture produces identical output; suites green.
- Status row set to Review with diff stat, test tails, the grep proving no module opens the legacy per-step files for
  writing, and the controller's checklist (run a 2,000-step headless probe and confirm one events.jsonl, row counts
  per kind, and `pokeagent review run` on it).

## Report

Diff stat, test tails, wc -l line, the reader-switch list (module -> view), anything you could not switch and why.
