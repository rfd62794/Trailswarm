# PokeAgent: Curriculum build selection - pick each slot's start state Go-Explore style over (checkpoint or leg, team build), and split a stalling segment at its slowest map transition

**Depends on `Save_Library_And_Party_Gate_Directive.md` merged** (it adds `src/pokeagent/statelib/library.py` with the library index `runs/states/library.json`, `src/pokeagent/team_fp.py` with `build_key`, and `src/pokeagent/party_rules.py`). If `git grep -n "def build_key" -- src/pokeagent/team_fp.py` finds nothing at the start of the run, stop and write that in the Status row; do not recreate those modules. Base: a main that contains that directive. <!-- new: src/pokeagent/statelib/library.py --> <!-- new: runs/states/library.json --> <!-- new: src/pokeagent/team_fp.py --> <!-- new: src/pokeagent/party_rules.py -->

## Why this exists

Robert, 2026-11-14: keep a library of checkpoints and legs for alternative team builds, so a bad build (the wild-Kakuna party) is just one cell among others and the swarm learns which builds reach the next checkpoint fastest.

Today the curriculum has no notion of build. `tools/seg_sched.py` `Curriculum.next_job` picks a segment, then starts it from the single best checkpoint file for the segment's start name:

```
job = self._job(seg, kind, n, ss.ckpt(self.root, seg.start), st)   # tools/seg_store.py ckpt(root, name) -> Path | None
```
`ckpt` is "<name>.best.state beats <name>.state" (plus a ledger pick via `statelog.pick`). Every slot therefore trains from the same team, and a run launched from a tainted state stamps tainted checkpoints (Claude measured this on 2026-11-14: `to_pewter.state` re-stamped by a drill that began from a Kakuna leg state). Drills pick the worst leg by waste (`src/pokeagent/legs/schedule.py` `rank`, `pick`) and then load `S.newest(sd, map, *entry)`, the newest leg state of that key, with no regard to team.

Splitting is failure-driven only: `tools/seg_split.py` `maybe_split(doc, root=None, par_fn=None)` cuts a segment at `cut_maps(...)` (maps reached by repeated failed attempts) when `should_split(st)` or `should_split_long(st, par)`. A segment that is slow or stalls on one map transition but still sometimes solves gets cut at a map chosen from FAILED attempts, not at its slowest transition.

The machinery already exists for the Go-Explore idea (`src/pokeagent/goexplore/archive.py`, `select.py`); this directive points it at (state, build) cells.

## Scope (in this order)

1. `src/pokeagent/statelib/cells.py` <!-- new: src/pokeagent/statelib/cells.py --> - turn library entries into an `Archive` of cells and record tries. Under 120 lines.
2. `src/pokeagent/statelib/start_pick.py` <!-- new: src/pokeagent/statelib/start_pick.py --> - the start-state picker (exploit / alternative / under-tried shares). Under 140 lines.
3. `src/pokeagent/statelib/slow_cut.py` <!-- new: src/pokeagent/statelib/slow_cut.py --> - the slowest-transition cut finder. Under 100 lines.
4. `tools/seg_sched.py` - `_job` and `next_job` use the picker; the job carries `build` and `cell`.
5. `tools/seg_ingest.py` - `build_attempt` records the job's `build` and `cell` on the attempt.
6. `tools/seg_split.py` - `maybe_split` consults `slow_cut` for a long or stalling segment.
7. `src/pokeagent/legs/schedule.py` - `pick` chooses the leg state by build via the picker (clean only).
8. Tests: `tests/test_statelib_cells.py`, `tests/test_statelib_start_pick.py`, `tests/test_statelib_slow_cut.py`, `tests/test_seg_sched_builds.py` <!-- new: tests/test_statelib_cells.py --> <!-- new: tests/test_statelib_start_pick.py --> <!-- new: tests/test_statelib_slow_cut.py --> <!-- new: tests/test_seg_sched_builds.py -->.

## The work

Existing facts, pasted (the worktree cannot be searched). `uv run python --version` prints `Python 3.12.12`.

```
# src/pokeagent/goexplore/archive.py
@dataclass
class Entry:  cid: str; state: str; goals: int; steps: int; hp: float = 0.0; n_seen: int = 0
              novelty: float = 0.0; parent: str | None = None; lineage: str = "organic"
def score(e: Entry) -> tuple[int, int, float]:        # (goals, -steps, hp): bigger is better
class Archive:  cap; entries: dict[str, Entry]; offer(e) -> bool (strict improvement replaces, keeps n_seen); mark_seen(...)
# src/pokeagent/goexplore/select.py
def rarity(n_seen) -> float   # 1/sqrt(n_seen+1)
def weight(e: Entry, on_route: bool = False) -> float   # progress * rarity;  progress = 1 + goals + min(5, novelty) + (1 if on_route)
def choose(archive: Archive, rng: random.Random, on_route: frozenset[str] = frozenset()) -> str | None   # weighted draw, seeded, no mutation
# tools/seg_sched.py
class Curriculum: refresh(), choose(gm=None) -> (kind, seg) | None, _job(seg, kind, n, start: Path, st: dict) -> dict, next_job(n) -> dict | None
# a job dict: {"key", "kind", "start": str(path), "stop": ["--stop-at-goal", g] | ["--stop-at-map", str(m)], "steps", "tag", "seed", [explore_rate], [starter]}
# tools/seg_store.py: Segment(key, goal, start, end, stop_goal, stop_map); layout(doc); stat(doc, key) -> {"attempts": [...], "n", "solves", "best", "confirmed"}; ckpt(root, name) -> Path | None
# tools/seg_split.py: maybe_split(doc, root=None, par_fn=None) -> list[str]; cut_maps(attempts, earlier=frozenset(), run_dirs=None) -> list[int]
#   should_split(st) / should_split_long(st, par); an attempt: {"run","solved","frames","steps","maps","tagged","est","stalled","budget","seed",...}
# run transitions (runs/<run>/transitions.jsonl): {"step": 2, "from": [14, 0, 10], "to": [2, 39, 18], "moved": true, "source": "agent", ...}  (from/to = [map, x, y])
# src/pokeagent/legs/schedule.py: rank(legs, states, drills, now, min_samples=3) -> worst-first leg records; pick(root, n=0, now=None, states_dir=None) -> {"leg","state","steps","key"} | None
# library entry (from the first directive): {"tier": "checkpoint"|"leg", "name", "segment", "state", "build", "verdict": "clean"|"violation"|"unknown",
#   "run", "seed", "parent", "created", "metrics": {"steps", "faints", "readiness", "readiness_boss"}}
```

### Cells and tries (cells.py)

- A cell is `(name, build)` for tier `checkpoint` (the cell key `cid = f"{name}|{build or 'unknown'}"`) and `(segment, build)` for legs (`cid = f"leg:{segment}|{build}"`). Only entries with verdict `clean` (or `unknown` when `allow_unknown=True`, default False) become cells; a `violation` entry never does.
- `to_archive(entries, goals_index) -> Archive`: one `goexplore.archive.Entry` per cell holding the best state for the cell (`archive.offer` keeps the better one by `score`): `goals` = the checkpoint's index in `src/pokeagent/goals.py` `GOALS` (a leg takes its segment's start index), `steps` = `metrics.steps` or a large constant when null, `hp` from the fingerprint party HP fraction, `n_seen` from the tries file, `state` the state path, `parent` the parent state name.
- Tries file `runs/states/build_tries.json` <!-- new: runs/states/build_tries.json -->: `{"v": 1, "cells": {cid: {"tries": n, "solves": n, "last": iso}}}`, written atomically with `pokeagent.goexplore.store.atomic_write`. `record_try(root, cid, solved)` increments. Tries are updated from the ATTEMPT record (see ingest below), once per ingested attempt.

### Start-state picker (start_pick.py)

```
SHARES = {"exploit": 0.60, "alternative": 0.25, "promising": 0.15}   # named constants, untuned; overridable by runs/curriculum_builds.json {"shares": {...}} (read once per call; a missing or malformed file means the defaults)
def pick_start(entries, segment_start: str, rng: random.Random, tries: dict, shares=SHARES) -> Pick | None
@dataclass(frozen=True)
class Pick:  state: str; build: str | None; cell: str; mode: "exploit" | "alternative" | "promising"; why: str
```
Behaviour, deterministic for a seeded `rng` (never the global `random`):
- Candidates are the clean cells whose checkpoint `name` equals `segment_start` (the segment's start checkpoint). None when there are none (the caller then uses `ss.ckpt` unchanged, which keeps today's behaviour for a library that does not exist yet).
- With one candidate build the pick is always that build (mode `exploit`).
- Else draw the mode from `shares` with `rng`. `exploit`: the best build by `(readiness desc, steps asc, faints asc)` from `metrics`, nulls last; this is "the best build at the furthest checkpoint": the picker is called for the segment the curriculum chose, which is already the frontier segment for `frontier` jobs. `alternative`: `goexplore.select.choose` over the Archive of the NON-exploit candidates (weighted by rarity, so rarely-tried builds win). `promising`: among candidates with fewer than `PROMISING_MIN_TRIES = 3` tries, the one with the best `readiness` (null readiness ranks last); when none qualifies, fall back to `alternative`.
- `why` is a one-line explanation that lands in the curriculum log line and the job (`build X, mode alternative, 1 try, readiness 0.4`).

### Wiring (seg_sched.py, seg_ingest.py, legs/schedule.py)

- `Curriculum.next_job`: where it calls `ss.ckpt(self.root, seg.start)` for the chosen segment (and for the `repro` branch), first try `pick_start(...)` on the library entries (`statelib.library` load; a missing or unreadable library means no pick) with an `rng = random.Random(self.session + n)`; use `Path(pick.state)` when it exists, else `ss.ckpt` exactly as today. Add `build`, `cell` and `pick_mode` to the job dict only when a pick was used. Keep `next_job`'s other branches (confirm, broken replay) unchanged: a confirm run must start from the state that produced the solve.
- Log line `curriculum: ... from <state name> (build <b>, <mode>)` extends the existing `self.log(f"curriculum: ...")` line.
- `seg_ingest.build_attempt`: add `"build": job.get("build")` and `"cell": job.get("cell")` where the job record for the tag is available (`_job_record(root, tag)` exists at `tools/seg_ingest.py` line ~185; read it to see how the job record is looked up and reuse it); both are additive keys, so old attempts read as None. After `record_attempt` folds an attempt in, call `record_try(root, cell, solved)` when `cell` is set.
- `src/pokeagent/legs/schedule.py` `pick`: after the worst leg is chosen, find library entries of tier `leg` for that leg key `(map, entry x, y)` with verdict clean; when more than one build exists use `pick_start` over them (segment_start = the leg's key); when the library has none, keep `S.newest(sd, ...)` as today. A leg state whose verdict is `violation` is never returned (also when there is no library: read the sidecar and apply `party_rules.verdict`).

### Auto-split at the slowest map transition (slow_cut.py, seg_split.py)

`slowest_transition(run_dirs, earlier=frozenset()) -> int | None`: for each given finished run directory read `transitions.jsonl`; a map transition is a record whose `to[0]` differs from `from[0]`; the cost of a map is the number of steps spent in it before leaving (steps between its entry and the next map change), summed over the runs; return the map id with the highest MEDIAN cost per run that is not in `earlier` (maps already inside earlier segments), is not the segment's first map, and was seen in at least `MIN_RUNS = 3` runs. None when no map qualifies. Use `tools/seg_split.py` `_jl` as the model for tolerant reads (a missing or bad file counts as no data).
In `tools/seg_split.maybe_split`: when a top-level segment is "long or stalling" (`should_split_long(st, par)` is true, or at least `STALL_MIN = 2` of the last `WINDOW` attempts have `stalled` true) and `cut_maps(...)` returned nothing, try `slowest_transition` over the same `run_dirs` the failure path builds (existing code: `root / "runs" / a["run"]` for the window's attempts, here including SOLVED attempts since a long segment may be solving slowly); when it returns a map, set `doc["splits"][seg.goal] = [that map]` and report the goal as split. Failure-driven splitting stays first and unchanged; the slow cut is the fallback only. Existing `split_retry_at` retry logic applies to a None result.

## What NOT to do

- Do not change `src/pokeagent/goexplore/archive.py` or `src/pokeagent/goexplore/select.py` (reuse them unmodified), the Go-Explore runner, `tools/swarm.py`'s CLI, or `ss.ckpt` semantics when no library exists.
- Do not pick a state whose verdict is `violation`; do not pick synthetic-lineage states (`statelog` already skips them; keep that).
- Do not rename segments or goals. Do not change the confirm / broken-replay / repro start-state logic.
- No emulator runs, no ROM, no reading `runs/` in tests; build entries, state files, attempts and `transitions.jsonl` in `tmp_path`. Never start the swarm.
- No new dependency; no randomness outside a passed-in `random.Random`.
- Do not state where any game copy came from.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_statelib_cells.py tests/test_statelib_start_pick.py tests/test_statelib_slow_cut.py tests/test_seg_sched_builds.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_goexplore_archive.py tests/test_goexplore_select.py tests/test_seg_sched_grades.py tests/test_seg_split_rejoin.py tests/test_swarm_continuous.py
```
Expected: no new failures (existing files, unchanged). Claude ran this exact command on main while writing the directive; the tail is in the PR description.

```
git diff --stat origin/main -- src/pokeagent tools
```
Expected: the files in Scope only.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-curriculum-build-selection-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `to_archive` builds one cell per `(name, build)` from clean entries only, keeps the better state per cell, and never includes a `violation` entry. <!-- test: tests/test_statelib_cells.py -->
- [ ] `pick_start` is deterministic for a seed, returns the only build when there is one, draws exploit/alternative/promising by `SHARES` (over 2,000 seeded draws the observed shares are within 0.05 of the configured ones), `promising` falls back to `alternative` when nothing is under-tried, and returns None for no candidates. <!-- test: tests/test_statelib_start_pick.py -->
- [ ] `slowest_transition` returns the map with the highest median step cost seen in at least 3 runs, excludes `earlier` maps and the first map, and returns None on missing or malformed logs. <!-- test: tests/test_statelib_slow_cut.py -->
- [ ] `Curriculum.next_job` uses the picker when a library exists (job has `build`, `cell`, `pick_mode`), and is byte-for-byte unchanged in behaviour when it does not; confirm and replay jobs never use it. <!-- test: tests/test_seg_sched_builds.py -->
- [ ] A drill never loads a `violation` leg state; with two clean builds for one leg key the picker chooses between them. <!-- test: tests/test_seg_sched_builds.py -->
- [ ] `maybe_split` falls back to the slowest transition for a long or stalling segment with no failure-driven cut, and the failure-driven cut still wins when it exists. <!-- test: tests/test_seg_sched_builds.py -->
- [ ] The five existing test files above pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, the constants (`SHARES`, `PROMISING_MIN_TRIES`, `MIN_RUNS`, `STALL_MIN`) and where each is overridable. Then the checks Claude runs afterwards with the ROM and the real `runs/` (Devin cannot): with the swarm paused, run `uv run pokeagent states library build`, start `uv run python tools/swarm.py --continuous --plan curriculum --save-leg-states` for a few minutes and read the `curriculum:` log lines to confirm start states vary by build and no violating state is chosen; read `runs/states/build_tries.json` to confirm tries accumulate; confirm one auto-split on a real stalling segment by reading the `splits` key of `runs/segments.json` <!-- new: runs/segments.json -->.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The save-library directive merged first, and the post-merge ROM checks in the Report section, run by Claude. Nothing else blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
