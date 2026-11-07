# PokeAgent: segment scorecard - grade segments (solved / optimized / stale / broken), let the grades steer the curriculum, split and rejoin on evidence, and name test suites

**Read first (all in the worktree; if one is missing, stop and write that in the Status row):** `tools/segments.py` (`render`, the table), `tools/seg_store.py` (`Segment`, `stat`, `window`, `rate`, `is_solved`, `expected_frames`, `accepted`, `best_frames`, `chain`, `layout`, `WINDOW`, `SOLVED_RATE`, `ckpt_valid`, `refusal`), `tools/seg_sched.py` (`Curriculum.next_job`, `SHARES`, `SHARE_UNSOLVED/FRONTIER/POLISH`, `POLISH_EXPLORE_RATE`, `CONFIRM_TRIES`, the hold handling), `tools/seg_split.py` (`MIN_ATTEMPTS`, `SPLIT_RATE`, `MAX_CUTS`, `MIN_REACH`, `trusted_failures`, `cut_maps`, `should_split`, `maybe_split`, `reset`), `tools/seg_ingest.py` (`build_attempt`, `record_attempt`, `record_confirm`, `ingest`), `tools/seg_hold.py` (PR #146: `HoldFile`), `tools/seg_janitor.py`, `tools/swarm.py` (the `--plan curriculum` argument, ~line 218), `tools/ab.py` (arguments, ~lines 103-112), `src/pokeagent/legs/par.py` and `src/pokeagent/legs/drill.py` (`par_frames_for`, `map_par`), `src/pokeagent/legs/grid.py`, `src/pokeagent/statefp.py` (state fingerprints; lineage is PR #147, in review), `src/pokeagent/stalls.py`, `src/pokeagent/atlas/map_names.json`, `tests/` files that already cover the seg_* tools (list them with `git ls-files tests | grep seg`). **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "How do we start grading segments looking for things like solved, and optimized, so we balance new solves as well as optimization of prior segments. And when do we look at granular segment breaking and rejoining? Do we need to consider building a roster of segment variety for different types of tests, runs, and analysis investigations?"

Today `tools/segments.py` prints one table (attempts, rate, best, expected, confirmed, share) and the scheduler hands out slots by fixed shares: UNSOLVED 0.40, FRONTIER 0.45, POLISH 0.15 (`seg_sched.SHARES`), with a pending CONFIRM replay first. `is_solved` is a single boolean (rate over the last 20 attempts >= 0.9). Nothing says whether a solved segment is OPTIMIZED (near par), STALE (not touched lately), or BROKEN (a code change collapsed it), the shares do not react to how healthy the frontier is, splitting happens only on a low solve rate (`SPLIT_RATE` 0.30 after 20 attempts) and only at map entries, there is no rejoin, and there is one flat list of segments for every purpose. Live numbers today: 52 stat entries in `runs/segments.json`, e.g. `to_viridian` 60 attempts window, n=5506, solves 3841, best 240 frames confirmed.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive`, unrelated: ignore it and say so if it fails for you). `runs/`, `roms/`, `baselines/` are gitignored: no ROM or `runs/` in your worktree. Every test builds a FIXTURE `segments.json` doc in `tmp_path` (shape below) and fixture checkpoint files; no emulator runs.
- `runs/segments.json` keys: `version, ingested (list of run names), splits, stats, calib`. `splits` = `{goal: [cut map ids]}` (e.g. `{"ss_anne_captain": [97, 99], "to_bill": [36], "ss_anne_2f": [90, 93], "pokemon_fan_club": [100, 85, 197, 46]}`); `calib` = `{"frames": N, "steps": N}` (frames per press, `seg_store.fps(doc)`). `stats[key]` has exactly the keys `attempts, solves, jobs, split_retry_at, n, best, confirmed`. Example (real): `to_viridian`: `attempts` (list, capped at `KEEP_ATTEMPTS = 60`), `n` 5506, `solves` 3841, `jobs` 70, `split_retry_at` 500, `best` = `confirmed` = `{"frames": 240, "steps": 59, "run": "explore-20261107-120518-13872", "seed": 71065, "starter": "charmander", "explore_rate": 0.5, "box_pace": 16, "budget": 1500, "confirmed": True, "tries": 1, "rejected": False, "state": None, "input": None, "start": None, "start_sha": "5eec88..."}`.
- An attempt (real keys): `{"run": "explore-20261103-013155-27280", "solved": true, "frames": 755, "est": true, "steps": 75, "seed": 1003, "starter": "bulbasaur", "explore_rate": null, "box_pace": null, "budget": null, "maps": [38], "tagged": false, "outside": 0}`. **There is NO `git_sha`, NO timestamp, NO blackout/stall/loop count in an attempt today.** The run directory name carries local time (`explore-YYYYMMDD-HHMMSS-<pid>`) and the run's `meta.json` carries `git_sha`. Additions this directive makes to `seg_ingest.build_attempt` (additive; old attempts simply lack them and are graded `unknown` where a column needs them): `git_sha` (from `meta.json`), `ts` (epoch seconds parsed from the run dir name, local time), `blackouts` (count of `runs/battles.jsonl` records for the run with `outcome == "blackout"`), `stalled` (bool: `runs/stalls/<run>.json` exists), `provenance` (`organic` | `synthetic` | `unknown`, from the start state's lineage via `statefp` / PR #147; `unknown` when the lineage reader is absent; never guessed), `loops` (count of `kind == "veto"` rows in the run's `loops.jsonl` when that file exists, else None). Compute `blackouts` from ONE pass over `battles.jsonl` per `ingest` call (an index by run), never one scan per run.
- Constants in the code today: `seg_store.WINDOW = 20`, `SOLVED_RATE = 0.9`, `PENALTY_FRAC = 0.5`, `PENALTY_FLOOR = 600`, `FRAMES_PER_STEP = 10.5`, `KEEP_ATTEMPTS = 60`; `seg_split.MIN_ATTEMPTS = 20`, `SPLIT_RATE = 0.30`, `MAX_CUTS = 4`, `MIN_REACH = 2`; `seg_sched.SHARE_UNSOLVED = 0.40`, `SHARE_FRONTIER = 0.45`, `SHARE_POLISH = 0.15`, `POLISH_EXPLORE_RATE = 0.5`, `CONFIRM_TRIES = 2`, `BUDGET_MULT/MIN/MAX/DEFAULT = 3, 1500, 6000, 3000`. `cut_maps` cuts only at MAP entries (`stop_map`); a sub-segment key is `"<goal>@<map hex>"` or `"<goal>@end"`. A job stops at `--stop-at-goal` or `--stop-at-map` (`tools/explore_headless.py`); there is NO stop-at-event condition.
- Par: `legs.par.map_par(grids, map, entry, exit) -> (frames, path) | None` is the exact cheapest route across ONE map's grid (needs the ROM grids: `legs.grid.rom_grids(rom)`, gitignored/None without a ROM); `legs.drill.par_frames_for(spec, rom)` wraps it for a drill leg. **There is no function for the par of a whole multi-map segment**; add `segment_par(maps_path, entries_exits, grids)` (sum of `map_par` per map traversed + `FRAME_WALK` for each leaving press) in a new pure module and return None when any leg is unknown. The controller supplies the ROM.
- The hold list (PR #146, `seg_hold.HoldFile`, `runs/curriculum_hold.json`) removes a segment from every category until it expires; the scorecard must show a held segment as `held` with the reason and never schedule it.
- Start-state health: `seg_store.ckpt_valid(root, name)`, `seg_store.refusal(root, name) -> str | None` (the reason a checkpoint is refused), the state fingerprint sidecars (`statefp`, `<state>.fp.json`), and the lineage/ledger of PR #147 (in review: if `pokeagent.statelog` or a lineage reader is importable use it for an "organic starts only" grade, otherwise leave the column `n/a` behind a small seam `start_grade(root, seg) -> str`).
- Existing review CLI: `Review_Replay_Tools_Directive.md` (queued) creates `src/pokeagent/cli_review.py` with `register(sub)`; this PR adds the `segments` subcommand. If `cli_review.py` already exists on your branch, ADD a `segments` subparser and handler to it; if it does not, create the file with ONLY `segments`, register it in `cli.py` (one import, one `register(sub)` call), and say in the report that the two PRs both touch `cli_review.py` (the second to merge resolves it by keeping both subcommands).
- **Files and semantics you must NOT change:** `seg_store.accepted`, `chain`, `best_frames`, `is_solved`, `rate`, `window`, `expected_frames` (the "chain bests" semantics: accepted = the fastest CONFIRMED solve, else fastest seen, else estimated), `record_confirm`'s acceptance rule, `seg_ingest` candidate/confirm gating, `ss.save` format (additions to attempts only).

## 3. Scope (one PR, in order)

1. Grades: `src/pokeagent/segment_grades.py` (pure) + the additive attempt fields in `seg_ingest.build_attempt`.
2. Allocation: the scheduler reads the grades (`seg_sched.py`).
3. Split and rejoin rules (`seg_split.py` additions, scheduler probe job).
4. Roster: `runs/segment_sets.json`, `tools/seg_suites.py`, `--suite` for `tools/swarm.py --plan curriculum` and `tools/ab.py`.
5. `pokeagent review segments` (text + `--json`, handler-tested).
6. Tests.

## 4. The work

Every constant is NAMED with a comment that it is an untuned first value. Each new module under 300 lines.

### 4.1 Grades (`segment_grades.py`)

```python
OPT_TOL = 0.15              # optimized: confirmed best within 15% of par
PLATEAU_ATTEMPTS = 10       # no-par fallback: this many polish attempts since the best did not beat it by more than PLATEAU_GAIN
PLATEAU_GAIN = 0.01
STALE_DAYS = 3              # no attempt for this long = stale
BROKEN_MIN_AFTER = 5        # attempts with the newest git_sha needed before calling a segment broken
BROKEN_DROP = 0.40          # solve rate must fall by this much versus the attempts before the newest git_sha
BROKEN_MIN_BEFORE = 0.70    # ... and have been at least this high before

@dataclass(frozen=True)
class Grade:
    key: str
    solved: bool; optimized: bool; stale: bool; broken: bool; held: str | None
    rate: float | None; attempts: int; best: int | None; expected: float | None; par: float | None
    health: float | None                       # best / expected, 0..1 (1.0 = a typical attempt costs the same as the best); None without both
    blackout_rate: float | None; stall_rate: float | None; loop_rate: float | None    # per attempt over the window; None when the attempts lack the field
    start: str                                  # "ok" | the ss.refusal(...) reason | "n/a" (the lineage seam)
    provenance: str                             # "organic" | "synthetic" | "mixed" | "unknown": where the solves/best came from (4.1)
    synthetic_only: bool                        # solves/best exist ONLY from synthetic-lineage starts: a hypothesis, not a result
    last_ts: float | None; sha_before: float | None; sha_after: float | None
def grade_segment(seg, st, per_step: float, par: float | None, now: float, hold: str | None = None, start: str = "n/a") -> Grade
def grade_all(doc, root, now, par_fn=None, hold_file=None) -> list[Grade]      # one Grade per ss.layout(doc) segment, in chain order
```
- `solved` = the existing `ss.is_solved(st)` (do not redefine). `held` = the hold reason from `seg_hold` or None.
- `optimized` = `solved` AND the accepted best is CONFIRMED (`st["confirmed"]`, not `est`) AND (with `par`): `best <= par * (1 + OPT_TOL)`; without `par`: the PLATEAU rule (the last `PLATEAU_ATTEMPTS` SOLVED attempts since the best was set did not beat it by more than `PLATEAU_GAIN`, and there are at least that many). `par` comes from `par_fn(seg, st)` (the pure `segment_par` of 4.0 below, `None` without a ROM or route); a None par never raises.
- `stale` = the newest attempt `ts` is older than `STALE_DAYS`, or the segment has no attempts with a `ts`/a derivable run time (derive from the run name when `ts` is absent).
- `broken` = attempts carry `git_sha`; split the window at the NEWEST sha: `after` = attempts with it (at least `BROKEN_MIN_AFTER`), `before` = the attempts before (at least `BROKEN_MIN_AFTER`); broken iff `rate(before) >= BROKEN_MIN_BEFORE` and `rate(after) <= rate(before) - BROKEN_DROP`. Attempts without `git_sha` -> `broken` False (unknown), never guessed. Report `sha_before`/`sha_after` rates.
- `health` = `best / expected` using `ss.best_frames` and `ss.expected_frames` (the failure-penalised expected cost). The columns blackout/stall/loop rates are the means of `blackouts > 0`, `stalled`, `loops` per attempt over `ss.window(st)`.
- **Provenance and the `synthetic_only` grade (standing rule, section 7):** the `provenance` column is `organic` when every solved attempt in the window started from an organic state, `synthetic` when every one did not, `mixed` otherwise, `unknown` when no lineage is available. `synthetic_only` is True when the segment has solves (or an accepted best) and NONE of them is organic: such a segment is shown as a HYPOTHESIS - never counted as `solved` for the shares or the chain, never `optimized`, never the accepted best of the chain (the existing rule that only organic starts count for bests is preserved and tested, not changed), and the scheduler gives it an "organic reproduction" job (a normal attempt from an organic start) at priority just below a broken regression replay; when an organic run solves it the grade promotes (`synthetic_only` False, provenance `mixed`/`organic`) with the same semantics as state promotion. Drills, A/B and planning may use synthetic attempts freely; suites in 4.4 carry the provenance of their members.
- `segment_par(...)` lives in `segment_grades.py` or a sibling `segment_par.py` (pure; fixture grids in tests): sums `legs.par.map_par` over the maps of the best run's `maps` path using its entry/exit tiles (taken from the accepted best's recorded warps when known, else None).

### 4.2 Allocation: the grades steer the shares (`seg_sched.py`)

Keep `SHARE_*` as the BASE shares; `Curriculum.next_job` computes effective shares with a new pure function `effective_shares(grades, base=SHARES) -> dict` (in `segment_grades.py`):
- **Polish** share: `base polish` scaled by the number of `solved and not optimized and not held and not broken` segments: `polish = min(POLISH_MAX = 0.35, base_polish * (1 + n_unopt / POLISH_RAMP))` with `POLISH_RAMP = 5`; zero such segments -> polish drops to `POLISH_MIN = 0.05`. The freed or added share is taken from / given to the other two proportionally (shares always sum to 1).
- **Frontier health** `fh` = the frontier segment's `health` (or its window rate when health is None; 0.5 when unknown). New-solve shares and their exploration scale with it: the unsolved + frontier groups together keep their combined share but `explore_rate` of those jobs = `EXPLORE_MIN + (EXPLORE_MAX - EXPLORE_MIN) * (1 - fh)` with `EXPLORE_MIN = 0.0`, `EXPLORE_MAX = 0.6` (bad frontier health -> more exploration/scouting; good -> exploit with rate near 0). `POLISH_EXPLORE_RATE` (0.5) is unchanged for polish jobs.
- **Broken first:** a segment graded `broken` whose accepted best is replayable (`ss.replayable`) gets a CONFIRM-style regression replay BEFORE normal picks (priority right after a pending confirm): the scheduler reuses the existing confirm job path to replay the accepted best from its recorded input; the job's result is ingested by the existing `record_confirm` untouched. At most one such job per segment per `BROKEN_RECHECK_HOURS = 6`. A broken segment with no replayable best is shown as broken in the scorecard and left to the normal UNSOLVED rotation.
- `held` segments are still excluded everywhere (unchanged); `stale` solved segments become eligible for POLISH ahead of fresh ones (stale first within the polish group).
- Behaviour with no new data (old attempts without `git_sha`/`ts`) must be IDENTICAL to today's scheduling: `effective_shares` returns the base shares and unchanged explore rates when every grade column is unknown. A test pins this.

### 4.3 Split and rejoin (`seg_split.py` additions)

- **Existing split rule stays:** `st["n"] >= MIN_ATTEMPTS`, window full, `rate < SPLIT_RATE`, trusted cut maps exist. **New trigger (too long to retry whole):** `median solve frames > SPLIT_PAR_MULT * par` (`SPLIT_PAR_MULT = 3.0`, needs `par`; skipped when par is None) with at least `MIN_SOLVES_FOR_LONG = 5` solves, and the same trusted cut maps (`cut_maps`) must exist. Same `maybe_split` bookkeeping (`splits`, `split_retry_at`).
- **Event-aware cut choice:** cuts remain MAP stops (the only stop condition that exists: `--stop-at-map`; do NOT add a stop-at-event). Among the candidate cut maps, rank them by how many goal-relevant EVENTS happen at or just before entering them in the trusted runs, so a cut lands after a heal (entering a Pokecenter map), a trainer win, an item gain or a level gain rather than arbitrarily: `event_support(run_dir, map_id)` (pure over fixture `decisions.jsonl` / `levels.jsonl` / `battles.jsonl`). Event cuts that cannot be expressed as a map stop are written to the scorecard as `cut_hints` (report only) so a later directive can add a stop-at-event condition. `MAX_CUTS` still caps the count.
- **Rejoin:** `should_rejoin(doc, goal, grades, pieces) -> bool`: every piece of the split is `solved and optimized` AND the joined (parent) segment has at least `REJOIN_PROBES = 2` consecutive probe solves whose frames are within `REJOIN_TOL = 0.10` of the SUM of the pieces' accepted bests (`seg_split.reset(doc, [goal])` then undoes the split). A probe is an ordinary parent-segment job (start = the parent's start checkpoint, stop = the parent's own end, `explore_rate` 0) scheduled by the curriculum as a `rejoin_probe` at share `REJOIN_SHARE = 0.05` only while the rejoin condition on the pieces holds; its attempts are tagged `rejoin` and kept apart from the pieces' stats. Pure functions + a small scheduler hook; no replay of concatenated input is attempted (there is no such mechanism).

### 4.4 Roster: named suites (`runs/segment_sets.json`, `tools/seg_suites.py`)

```json
{"version": 1, "suites": {
  "smoke":    {"rule": "first", "n": 5},
  "campaign": {"rule": "chain"},
  "stress":   {"rule": "worst_health", "n": 5},
  "variety":  {"rule": "per_map_type"},
  "starters": {"rule": "per_starter", "segments": ["to_viridian", "beat_brock"], "starters": ["bulbasaur", "charmander", "squirtle"]},
  "mine":     {"rule": "list", "segments": ["to_route3", "beat_misty"]}}}
```
- `seg_suites.resolve(name, doc, grades, root) -> list[Member]` where `Member = {"key", "starter": str | None}`: `first` = the first `n` of `ss.layout(doc)`; `chain` = every segment; `worst_health` = the `n` segments with the lowest `health` (None last), held ones excluded; `per_map_type` = one segment per map TYPE of its END map (classify with `atlas/map_names.json` names: `ROUTE_*` route, `*_CITY`/`*_TOWN` town, `*_GYM`/`*_HOUSE`/`*_MART`/`*_POKECENTER`/`SS_ANNE_*` indoor, `MT_*`/`*_CAVE`/`*_TUNNEL`/`DIGLETTS_CAVE` cave; anything else `other`), the first segment of each type in chain order; `per_starter` = the listed segments crossed with the listed starters (one Member each); `list` = explicit keys (unknown keys dropped with a warning). A missing or malformed file yields the built-in defaults above; a malformed suite is skipped on its own (like `seg_hold`).
- **Use:** `tools/swarm.py --plan curriculum --suite NAME` restricts the curriculum's candidates to the suite's segments (and passes `starter` per Member to the job's `--starter`); without `--suite` nothing changes. `tools/ab.py --suite NAME` expands to one A/B per Member (its start state = the segment's start checkpoint, its stop goal), reusing the existing per-goal flow; `tools/ab.py list` also lists the suites. Both read `runs/segment_sets.json` through `seg_suites` only.
- The suites are the "roster of segment variety" Robert asked for: smoke (fast CI-like check), campaign (the real chain), stress (the sickest five, for fixes), variety (breadth), starters (the three starters explored equally), mine (an investigation list).

### 4.5 `pokeagent review segments`

`pokeagent review segments [--json] [--root .] [--suite NAME] [--no-ingest]` prints the scorecard: one row per segment in chain order with the columns `segment, tries, rate, solved/optimized/stale/broken/held flags, best, par, expected, health, blackout%, stall%, loop%, start, share(effective), cut_hints`, then the effective shares and the frontier health used, and the rejoin candidates. Text by default; `--json` is the same data with sorted keys. Exit 0; exit 1 when any non-held segment is `broken`; exit 2 on an unreadable root. `tools/segments.py` keeps its table and gets ONE added line pointing at the scorecard (no other change; its tests stay green). The handler is tested by calling `cli_review.main([...])` / the handler function, never the entry point.

### 4.6 Tests (fixture `segments.json`, fixture checkpoints; no ROM, no emulator)

`tests/test_segment_grades.py`: each flag on fixture stats: solved (via `is_solved`), optimized with a fixture par (within/outside `OPT_TOL`) and with the plateau fallback, unconfirmed best is never optimized, stale by `ts` and by run-name time, broken by a sha split (high before, collapsed after) and NOT broken for too few attempts or no `git_sha`, `held` from a fixture hold file, health = best/expected, blackout/stall/loop rates with and without the fields, `start` from a fixture refusal; `segment_par` on a two-map fixture grid sums legs and returns None on a missing leg.
`tests/test_seg_ingest_grades.py`: `build_attempt` adds `git_sha`, `ts`, `blackouts`, `stalled`, `loops` from fixture run dirs and a fixture `battles.jsonl` (one pass for many runs), and old attempts without them load and grade as `unknown`; the `accepted` / `chain` results on the existing seg_store fixtures are byte-identical (the existing seg tests unedited and green).
`tests/test_segment_provenance.py`: provenance column for organic / synthetic / mixed / unknown fixtures; `synthetic_only` set for a segment whose only solves are synthetic; such a segment is not `solved`/`optimized` for the shares, is not a chain best (existing `chain` fixtures byte-identical), gets an organic-reproduction job, and is promoted by one organic solve; a missing lineage reader gives `unknown` and never `synthetic`.
`tests/test_seg_sched_grades.py`: `effective_shares` = base shares when nothing is graded (identical scheduling to today), more polish with more solved-not-optimized segments, zero such segments -> `POLISH_MIN`, shares sum to 1, explore rate rises as frontier health falls, held segments excluded, a broken replayable segment yields a regression confirm job before normal picks and only once per `BROKEN_RECHECK_HOURS`, stale-first within polish.
`tests/test_seg_split_rejoin.py`: the existing split rule unchanged (existing tests green); the long-solve trigger fires at `SPLIT_PAR_MULT` x par and not without par; event-ranked cut choice prefers a cut after a heal/trainer win/item/level gain on fixture run dirs; `cut_hints` lists event cuts that cannot be map stops; `should_rejoin` needs every piece solved+optimized AND `REJOIN_PROBES` probes within `REJOIN_TOL`; `reset` undoes the split.
`tests/test_seg_suites.py`: each rule on a fixture doc (first, chain, worst_health with held excluded and None last, per_map_type with the map-name classification, per_starter crossing, list with an unknown key), defaults when the file is missing or malformed, a malformed suite skipped alone, `--suite` restriction in the curriculum candidates, `tools/ab.py list` shows suites.
`tests/test_review_segments.py`: the handler prints the text table and `--json` on a fixture doc; exit 1 on a broken segment, 0 otherwise, 2 on a missing root; `--suite` filters rows.

## 5. What NOT to do

- No changes to the chain bests semantics (`accepted`, `chain`, `best_frames`, `is_solved`, `rate`, `window`, `expected_frames`, the confirm-acceptance rule). No new stop condition for explore_headless (no stop-at-event). No emulator runs by you; no `uv run pokeagent ...`. No new dependencies; each module under 300 lines.
- Do not change the base `SHARE_*` constants or `POLISH_EXPLORE_RATE`; the effective shares are computed on top, and with no grade data scheduling is exactly today's. Do not delete or rewrite anything under `runs/` (the only new runtime file is the optional `runs/segment_sets.json`, read-only for the code; the built-in defaults work without it).
- Do not claim a par you did not compute (None is fine); do not guess `git_sha` for old attempts; do not schedule a held segment.

## 6. Verification

- `uv run pytest -q tests/test_segment_grades.py tests/test_seg_ingest_grades.py tests/test_seg_sched_grades.py tests/test_seg_split_rejoin.py tests/test_seg_suites.py tests/test_review_segments.py` - new tests pass (paste the tail).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm the existing seg_* tests pass UNEDITED and that no forbidden semantics changed.
- **Controller validation (not Devin; the real `runs/` and ROM are on the laptop):** run the scorecard on today's `runs/segments.json` and check the flags against reality (for example `to_viridian` 3841/5506 solves with a confirmed 240-frame best should read solved and, with a ROM par, optimized or not; the segments with recent code changes should show their before/after rates); supply the ROM grids for `segment_par`; run one `--suite smoke` curriculum round.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-segment-scorecard-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.
- **Standing rule (Robert, 2026-11-07, verbatim): "We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."** Every learned record this work writes carries `"provenance": "organic" | "synthetic" | "unknown"`, taken from the start state's lineage (`statefp` lineage, PR #147: if it is not merged or a state has no lineage record the value is `"unknown"`, never guessed, and `unknown` is treated like organic for display and like synthetic for promotion: it can never be promoted by itself). Synthetic-born records are HYPOTHESES: usable for drills, A/B and planning, NEVER a chain best, a confirmed segment, a shared-memory veto or a KNOWLEDGE fact until an organic run reproduces them, at which point they are promoted (same semantics as state promotion). Tests use fixture lineage values only.

## 8. Completion criteria

- [ ] `segment_grades.py` (Grade, `grade_all`, `effective_shares`, `segment_par`) and the additive attempt fields in `seg_ingest.build_attempt`; old attempts grade as unknown
- [ ] `provenance` column and the `synthetic_only` grade (hypothesis until an organic run reproduces it); organic-reproduction job
- [ ] `seg_sched.py` reads the grades: polish share by unoptimized count, exploration by frontier health, broken-first regression replay, stale-first polish; identical to today with no grade data
- [ ] `seg_split.py`: long-solve trigger, event-ranked cuts with `cut_hints`, `should_rejoin` and the `rejoin_probe` job
- [ ] `runs/segment_sets.json` + `tools/seg_suites.py`; `--suite` on `tools/swarm.py --plan curriculum` and `tools/ab.py`
- [ ] `pokeagent review segments` (text + JSON, handler-tested); the six new test files pass; existing seg tests unedited and green; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures and every named constant, the effective shares on a fixture doc before and after grading, which flags the fixture doc produced, how `cli_review.py` was handled (existing file or created), which parts of the lineage/ledger seam were live or `n/a`, every existing test you had to touch, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 16:22 · robert-claude-laptop · none → Draft — Claude 2026-11-07: segment grades, grade-driven shares, split/rejoin, suites, review segments
- 2026-11-07 16:25 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; provenance column + synthetic_only grade; lint_override: dispatch-path-missing greenfield/gitignored
<!-- queue:end -->
