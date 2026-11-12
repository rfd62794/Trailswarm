# Trailswarm: self-grading memory - every learned entry earns or loses trust from outcomes, and a wrong fact stops steering the agent

**Size:** M. **Assignee:** devin.

**Depends on:** `Memory_Audit_And_Fact_Labels_Directive.md` merged (`docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md -->, `src/pokeagent/brain/audit.py` <!-- new: src/pokeagent/brain/audit.py -->, `src/pokeagent/brain/cleanplan.py` <!-- new: src/pokeagent/brain/cleanplan.py -->, `src/pokeagent/explorer/note_filter.py` <!-- new: src/pokeagent/explorer/note_filter.py -->, `src/pokeagent/cli_brain_memory.py` <!-- new: src/pokeagent/cli_brain_memory.py -->). Check with `git ls-files docs/MEMORY_FACTS.md src/pokeagent/brain/audit.py`. If either prints nothing, stop and write that in the PR description; do not recreate them. This directive BUILDS ON those labels (world fact / playthrough state / derived guess, and the area axis). It does not re-label a single field and it does not duplicate `brain audit` or `brain clean`: those remove known-bad content by static rules; this grades entries by what happened when the agent acted on them.

**Read first (all in the worktree; if one is missing, stop and say so in the PR description):** `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> (the labels), `src/pokeagent/explorer/loop_memory.py` and `loop_veto.py` (the no-progress ledger), `src/pokeagent/explorer/interaction_policy.py` and `retalk_veto.py` (where an entry is consulted), `src/pokeagent/explorer/interaction_record.py` (`close_interaction`, where a talk's outcome is known), `docs/directives/Loop_Memory_Directive.md`, `docs/directives/Segment_Scorecard_Directive.md`, `docs/directives/Family_Shared_Memory_Directive.md`, `tools/perf_probe.py`.

## 1. Why this exists

Measured and observed, not guessed:

- **2026-11-11 (tonight).** The shared memory held the Charmander starter ball in Oak's lab (map 40, interaction key `6,4,UP`) typed `info` with `done` true, written by an earlier run that had taken the starter. Every later run that loaded that memory refused the ball (`retalk_veto` -> `interaction_policy.decide` returns False for `info` with text, and for a giver with `done`) and pressed B for thousands of steps with party=0. The agent had the evidence that the entry was wrong (no progress, party still empty) the whole time and nothing used it. A separate fix (branch `fix/starter-giver-stall`) repairs the starter case; this directive is the general mechanism.
- **2026-11-08.** Red with its own maps.json never finished the potion goal in 600 steps; cold runs with no memory finished it by step 35. Memory made the agent worse, and the only remedy was to delete memory by hand.
- `interaction_policy.decide` (75 lines) reads `entry.get("type")` and `entry.get("done")` as truth. Nothing downgrades an entry that keeps being wrong. `loop_memory` already knows when an action in a situation made no progress, but it only vetoes the ACTION in that run; it never says "the memory that sent us here is wrong".

The principle: a persisted `done` or once-only flag on a playthrough-state field describes a previous save, so it is never trusted across runs. Every other learned entry starts unproven, gains trust when acting on it produced what it predicted, and loses it when it did not. A quarantined entry is ignored by decision code but kept (nothing is deleted) and reported.

## 2. Scope (one PR, in order)

1. `src/pokeagent/explorer/grades.py` <!-- new: src/pokeagent/explorer/grades.py --> (pure): the `Evidence` record, `grade_of(evidence) -> str`, thresholds as module constants.
2. `src/pokeagent/explorer/grade_store.py` <!-- new: src/pokeagent/explorer/grade_store.py --> : the sidecar file `memory_grades.json` beside `maps.json`: load, save (atomic), schema version, migration, the `Grades` class.
3. `src/pokeagent/explorer/grade_view.py` <!-- new: src/pokeagent/explorer/grade_view.py --> : `effective_entry(entry, ev, ...)`, the one function decision code calls so a doubtful or quarantined entry is seen as less than it claims.
4. Hooks (small edits, one call line each): `retalk_veto.py` (use), `interaction_record.py` (outcome of a talk), `loop_veto.py` (no-progress and progress signals), the warp-taken path in `memory_warps.py` (destination matched or not), and the run-end summary in `headless_loop.py`.
5. `brain grades` in `src/pokeagent/cli_brain_memory.py` <!-- new: src/pokeagent/cli_brain_memory.py --> (the file the dependency creates; add one subcommand) and a per-run summary row.
6. Tests (synthetic, no ROM): `tests/test_grades.py` <!-- new: tests/test_grades.py -->, `tests/test_grade_store.py` <!-- new: tests/test_grade_store.py -->, `tests/test_grade_view.py` <!-- new: tests/test_grade_view.py -->, `tests/test_grade_hooks.py` <!-- new: tests/test_grade_hooks.py -->, `tests/test_brain_grades.py` <!-- new: tests/test_brain_grades.py --> (all <!-- new -->).

Size rules: every new module and every `explorer/*.py` you touch stays under 300 lines (split first if an edit would cross it); no file over 600 anywhere.

## 3. The work

### 3.1 Evidence and storage

Do NOT add fields to `maps.json` entries. Evidence lives in a sidecar so `maps.json`, `tools/swarm_merge.py`, the journal and `brain clean` keep working unchanged and an older build that ignores the sidecar loses nothing.

```python
# grades.py
@dataclass
class Evidence:
    uses: int = 0            # times decision code consulted the entry
    confirms: int = 0        # acted on it and the outcome matched the prediction
    contradicts: int = 0     # acted on it and the outcome contradicted it, or a fresh observation disagreed
    recent: str = ""         # last RECENT_N outcomes, "C" confirm / "X" contradict, newest last
    last_confirmed_run: str | None = None
    last_run: str | None = None
    state_run: str | None = None   # run id that set a once-only flag on this entry (see 3.2)
```

Sidecar `memory_grades.json`, next to the `maps.json` it grades (same directory; resolve through the same path helper `MapMemory` uses; do not hardcode `runs/`):

```json
{"schema": 1, "entries": {"40:i:6,4,UP": {"uses": 0, "confirms": 0, "contradicts": 0, "recent": "", "last_confirmed_run": null, "last_run": null, "state_run": null}}}
```

Entry key `"{map}:{kind}:{key}"` where `kind` is `i` (interaction, key `x,y,FACING`), `n` (NPC results, key `x,y`), `w` (warp, key `x,y,BUTTON`). Rules for the store:

- Schema-versioned (`"schema": 1`). Load: a missing file is an empty store (every entry is `unknown`); a malformed file or a malformed entry is ignored, never raised over, never overwritten with less (rename a corrupt file to `memory_grades.json.bad` once, then start empty). A `schema` newer than this build reads as empty and is NOT saved over.
- Migration: an entry in `maps.json` with no sidecar record has grade `unknown`. Never write records for entries nobody has consulted. Nothing is ever deleted from the sidecar or from `maps.json`; a record for an entry that no longer exists in `maps.json` is kept and shown as `orphan` by `brain grades`.
- Writes are atomic (write a temp file in the same directory, then `os.replace`) and happen at the same flush points as the loop table fold (`PROMOTE_FLUSH_STEPS` and run end, see `loop_veto.fold`), never per step. Add no new thread.
- Merge between agents: the sidecar is per-checkout and is NOT merged by `swarm_merge` in this directive. Do not touch `tools/swarm_merge.py`. (Decided 2026-11-12: grades do not travel with shared facts, and are not shared between Red and Blue; a grade measures one agent's experience.)

### 3.2 Grades from evidence

Explicit thresholds, module constants in `grades.py`, all first values:

```python
RECENT_N = 8          # outcomes kept in `recent`
TRUST_CONFIRMS = 3    # confirms needed to be trusted
DOUBT_X = 2           # contradictions in `recent` that make an entry doubtful
QUARANTINE_X = 3      # contradictions in `recent` that quarantine it ...
QUARANTINE_RATIO = 2  # ... when they also outnumber confirms in `recent` by this factor
```

`grade_of(ev: Evidence | None) -> str`, evaluated in this order:

1. `ev is None` or (`ev.uses == 0` and `ev.recent == ""`) -> `"unknown"`.
2. `x = recent.count("X")`, `c = recent.count("C")`. `x >= QUARANTINE_X` and `x >= QUARANTINE_RATIO * max(c, 1)` -> `"quarantined"`.
3. `x >= DOUBT_X` and `x >= c` -> `"doubtful"`.
4. `ev.confirms >= TRUST_CONFIRMS` and `x * 3 <= c` -> `"trusted"`.
5. otherwise `"provisional"`.

Using the recent window (not lifetime totals) is deliberate: a quarantined entry that is probed and confirmed again recovers (X's age out of the window), and an old trusted entry that starts failing loses trust within a few uses.

Decision effect, in `grade_view.effective_entry(entry, ev: Evidence | None, *, run_id, probe_ok)` (it derives the grade with `grade_of(ev)` and reads `ev.state_run` for the strip below) which returns the entry decision code should see:

| grade | effect |
|---|---|
| `unknown`, `provisional`, `trusted` | the entry unchanged (today's behaviour, byte for byte) |
| `doubtful`, `quarantined` | `None` (as if never seen: `decide` then answers "untyped: unknown spot - talk once"), EXCEPT when `probe_ok` is true: one probe per entry per `PROBE_EVERY` (200) steps returns the entry unchanged. Import `PROBE_EVERY` from `loop_memory` and copy the `Loops.probes` bookkeeping style; do not invent a second probe clock. |

The entry stays in `maps.json` and in the sidecar. The probe is how a bad grade recovers: its outcome is recorded like any other use.

**Playthrough-state fields are never trusted across runs.** Using the dependency's labels: for any field that `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> classifies as playthrough state AND that is a once-only or completion flag (at least `done`, `gave`, `beaten`; take the list from the doc, do not retype it), `effective_entry` returns a COPY of the entry with that field removed unless the sidecar's `state_run` equals the current run id. Reconcile with the run stamp main already has: `interaction_record.py` writes `entry["done_run"]` when it sets `done`, and `interaction_policy.decide` compares it to `Need.run_id`. For `done`, treat that `done_run` as the state run (accept a match on either `done_run` or the sidecar `state_run`); do not add a second, drifting stamp for `done`. Stamp `state_run` only for flags that have no run stamp today (`gave`, `beaten`), at their write sites in `interaction_record.py` and `trainer_ledger.py`. The entry in `maps.json` is not edited. Never mutate the dict you are given; copy. If the dependency exposes the label table as code (look in the audit module for its area and field tables), import it; if it only exists as the document, add `src/pokeagent/explorer/fact_labels.py` <!-- new: src/pokeagent/explorer/fact_labels.py --> holding a small constant mirror and a test (`tests/test_fact_labels.py` <!-- new: tests/test_fact_labels.py -->) that parses the Markdown table in `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> and fails when the mirror and the document disagree, so the document stays the one source of truth.

### 3.3 Hooks: record the use, record the outcome

One narrow API, so hooks are one-liners and the logic lives in one place:

```python
# grade_store.py
class Grades:
    def use(self, key: str, run_id: str) -> None
    def outcome(self, key: str, confirmed: bool, run_id: str) -> None   # appends "C"/"X", trims to RECENT_N
    def grade(self, key: str) -> str
    def probe_ok(self, key: str, step: int) -> bool
```

`Grades` hangs off the same per-run object pattern as the loop ledger (`loop_veto.of(ctx)`; read `loop_veto.py` and copy the pattern as `grades.of(ctx)`). No global state.

Where an entry is consulted (record `use`, then call `effective_entry`):

- `retalk_veto.veto`: the entry from `entry_in_front(ctx)` is wrapped by `effective_entry` BEFORE the `entry.get("type") not in VETOABLE` test and before `decide(entry, need)`. Remember `ctx.consulted = (key, step)` so the outcome hook knows which entry steered the next press. Build the key from `ctx.view.m` and the facing tile exactly as `entry_in_front` does (an NPC at the facing tile -> kind `n`, key `x,y` of the NPC; else kind `i`).

Where the outcome is observed (record confirm or contradict for `ctx.consulted`, then clear it). Reuse existing signals; do not write a new detector:

- **Loop ledger.** `Loops.record` already knows whether a press progressed and returns a `LoopEvent` when a (situation, button) crosses `LOOP_NO_PROGRESS_N`. When the press followed a consult and a `LoopEvent` is produced, record a contradiction for that entry. When the press progressed (the ledger's own progress test), record a confirmation. Add the call at the end of `loop_veto.record`; do not change `LoopLedger`, its constants, or what it vetoes.
- **Talk outcome** (`interaction_record.close_interaction`, which already returns a verdict string for a closed talk): if the entry predicted `giver` and the talk produced a party or bag change (the existing code already computes the effect; reuse that value) -> confirm; if it predicted `giver` and nothing changed -> contradict; if it predicted another type and the type the recorder just derived differs from the stored one -> contradict; same type again -> confirm. This is also where a fresh observation that disagrees with the stored entry counts as a contradiction even when the agent was not steered by it.
- **Warp taken** (`memory_warps.py`, where `warp_taken` is recorded): the stored destination equals the map actually arrived at -> confirm; a different map -> contradict (a stored warp that sends you somewhere else is exactly a wrong fact). Key kind `w`.
- **Segment scorecard.** Do not add a second grader of runs. The per-run summary row (3.5) copies the segment result already computed by `tools/segments.py` / `seg_store` for the run's segment when it is available in the run dir, as two columns (`segment`, `segment_result`); nothing in grading reads it back.

Out of scope for v1 (list them in the PR description as follow-ups, do not build them): walls (`blocked`), ledge jumps, tile kinds, NPC positions. The key kinds are open-ended so adding them later changes no schema.

### 3.4 Safe to merge: byte-identical when nothing is graded

When the sidecar is empty or absent, or every consulted entry grades `unknown`, `provisional` or `trusted`, no decision may differ from today. Concretely: `effective_entry` returns the SAME object it was given in those cases (identity, so a test can assert `is`), and the persisted-state strip (3.2) is the one deliberate exception. Therefore:

- Make the strip a module constant `DISTRUST_PERSISTED_STATE = True` in `grade_view.py`, and have `brain grades` report how many entries in the loaded memory carry a persisted `done`/`gave`/`beaten` flag with no `state_run` matching a current run (that is how many entries behave differently from today).
- The perf probe's memory (`tools/perf_probe.py` builds its own under `--work-dir`) must have zero such flags, so its decisions are byte-identical; the controller checks that (Required from User). A synthetic test builds a memory with flags and shows the strip, and a memory without flags and shows identity.

### 3.5 Report

- `pokeagent brain grades [--maps PATH] [--text] [--top N]` (read-only; same `common` parent parser and `fileops.effective_data` as `audit`): JSON by default (sorted keys), plain summary with `--text`. Fields: `counts` per grade (`unknown`, `provisional`, `trusted`, `doubtful`, `quarantined`, `orphan`), `counts_by_kind`, `counts_by_area` (area from the dependency's labels), `distrusted_state_flags` (3.4), and `top_contradicted`: up to N (default 10) entries ordered by `contradicts` then lowest confirm ratio, each as `{"key": "40:i:6,4,UP", "grade", "uses", "confirms", "contradicts", "last_confirmed_run"}`. NEVER print dialogue or any `text`/`pages` content; keys, counts and grades only.
- A per-run summary row appended to `<run_dir>/grades.jsonl` at run end (through the existing `jsonl_buf`, one line): `{"run", "ts", "uses", "confirms", "contradicts", "newly_quarantined": [keys], "newly_recovered": [keys], "counts": {grade: n}, "segment", "segment_result"}`. A write failure is logged once and never stops a run (copy `Loops.row`).

### 3.6 Tests (synthetic only; no ROM, no real `maps.json`)

- `tests/test_grades.py` <!-- new: tests/test_grades.py -->: `grade_of` for each branch and each threshold boundary (one below, exactly at); recovery (a quarantined record whose recent window fills with `C` regrades `doubtful` then `provisional` or `trusted`); the outcome call trims `recent` to `RECENT_N`; `None` and empty -> `unknown`.
- `tests/test_grade_store.py` <!-- new: tests/test_grade_store.py -->: round trip; missing file; malformed file renamed to `.bad` and not crashed on; a newer `schema` is read as empty and not saved over; atomic save leaves no temp file; orphan records kept; old entries migrate to `unknown`; the sidecar path sits beside the given `maps.json`.
- `tests/test_grade_view.py` <!-- new: tests/test_grade_view.py -->: identity (`is`) for `unknown`/`provisional`/`trusted`; `quarantined` -> `None`; `doubtful` follows `probe_ok`; the entry passed in is never mutated; the persisted-state strip (`done`, `gave`, `beaten` removed on a copy, kept when `state_run` equals the current run); `decide` fed a stripped starter-ball entry (type `giver`, `done` true) answers `R_GIVER_FIRST`; `decide` fed the Oak's-lab shape (type `info`, text present, quarantined, so `None`) answers `R_NEW` (talk once).
- `tests/test_grade_hooks.py` <!-- new: tests/test_grade_hooks.py -->: the poisoned-entry scenario with a fake `ctx` (follow the fake-ctx style in `tests/test_explorer_behaviours.py` and any loop-veto test): an `info` entry consulted, a `LoopEvent` follows, repeated; assert it reaches `quarantined` after `QUARANTINE_X` contradicting uses (use the constant in the test), that after quarantine `retalk_veto.veto` returns `None` (lets the press through), and that a good entry whose presses progress reaches `trusted` after `TRUST_CONFIRMS` confirms and is never vetoed differently. A warp whose destination mismatches records `X`; a match records `C`. Nothing in `maps.json` is modified by any hook (assert the document is equal before and after).
- `tests/test_brain_grades.py` <!-- new: tests/test_brain_grades.py -->: counts, top-contradicted ordering, `--text` output contains no text from entries (plant a distinctive note string in a fixture entry and assert it never appears), exit 0 on an empty or missing sidecar.
- If `fact_labels.py` is added, `tests/test_fact_labels.py` <!-- new: tests/test_fact_labels.py --> as in 3.2.

## 4. What NOT to do

- Do not edit `runs/`, any `maps.json`, any ROM, save state or `baselines/`; do not look for them. Do not read or print any maps.json.
- Do not change `LoopLedger`, the loop constants, `loop_memory`'s shared table, `tools/swarm_merge.py`, `MapMemory`'s on-disk format, the edit journal ops, the segment scheduler or `seg_store`.
- Do not delete, rewrite or "clean" any memory entry from grading code. Grading only sets a sidecar record and changes what decision code sees. Removing content is `brain clean`'s job.
- Do not re-label fields or write a second field-classification table that can drift from `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md -->.
- Do not add a new no-progress detector, a new timer, a thread, or per-step disk writes.
- Do not touch the starter-ball fix (branch `fix/starter-giver-stall`); this directive must work with or without it. Do not special-case map 40 or any one entry anywhere in code.
- No network, no installs, no real emulator in tests. Never print dialogue.
- No changes under `src/pokeagent/game` or `src/pokeagent/cli.py`.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_grades.py tests/test_grade_store.py tests/test_grade_view.py tests/test_grade_hooks.py tests/test_brain_grades.py
```
Expected: all pass. Add `tests/test_fact_labels.py` <!-- new: tests/test_fact_labels.py --> if you created `fact_labels.py`.

```
uv run pytest -q -p no:cacheprovider tests/test_explorer_behaviours.py tests/test_brain_audit.py tests/test_brain_clean.py tests/test_perf_probe.py
```
Expected: same result as on your base commit, no new failures. Also run the existing interaction-policy, loop-memory and retalk tests: run `git ls-files tests` once, pick the files whose names contain `interaction`, `loop` or `retalk`, and run them the same way. Report any pre-existing failure separately. Do not run `tests/test_golden_red.py` (needs a ROM): report it NOT run and why.

```
uv run pokeagent brain grades --help
```
Expected: usage for `--maps`, `--text`, `--top`, exit 0.

```
wc -l src/pokeagent/explorer/grades.py src/pokeagent/explorer/grade_store.py src/pokeagent/explorer/grade_view.py src/pokeagent/explorer/retalk_veto.py src/pokeagent/explorer/loop_veto.py src/pokeagent/explorer/interaction_record.py src/pokeagent/explorer/memory_warps.py src/pokeagent/cli_brain_memory.py
```
Expected: each under 300.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.
- Free models only where the work touches model configuration (it should not).

## 7. Completion criteria

- [ ] Evidence per entry lives in a schema-versioned sidecar beside `maps.json`; old entries read as `unknown`; nothing is deleted from either file. <!-- test: tests/test_grade_store.py -->
- [ ] `grade_of` implements the pasted thresholds, with recovery through the recent window. <!-- test: tests/test_grades.py -->
- [ ] `effective_entry` returns the identical object for `unknown`/`provisional`/`trusted`, `None` for `doubtful`/`quarantined` (one probe per `PROBE_EVERY`), and strips persisted `done`/`gave`/`beaten` on a copy unless set this run. <!-- test: tests/test_grade_view.py -->
- [ ] Use is recorded at `retalk_veto`; confirm/contradict at the loop ledger signals, `close_interaction` and warp-taken; no new detector, no change to `LoopLedger`. <!-- test: tests/test_grade_hooks.py -->
- [ ] A poisoned entry is quarantined within `QUARANTINE_X` contradicting uses and the press then goes through; a good entry reaches `trusted`. <!-- test: tests/test_grade_hooks.py -->
- [ ] `brain grades` reports counts per grade, top contradicted entries and the distrusted-flag count, and never prints dialogue; a per-run row is appended to `grades.jsonl`. <!-- test: tests/test_brain_grades.py -->
- [ ] Existing suites listed in section 5 unchanged; all touched `explorer` files and new modules under 300 lines; nothing under `src/pokeagent/game` or `src/pokeagent/cli.py` touched.

## 8. Report

Findings first: the real names of the hook sites you used (and any that did not exist as described), whether `fact_labels.py` was needed, whether any file had to be split for size, and every judgement call on thresholds or keys. Then the command tails from section 5, with `tests/test_golden_red.py` reported NOT run. List the follow-ups left out (walls, ledges, tile kinds, NPC positions).

## Decisions (Robert, 2026-11-12: "I approve all")

1. Stripping persisted per-run flags (done/gave/beaten) unless `state_run` matches this run is accepted.
2. Grades are per checkout and per game: not merged by `swarm_merge`, not shared between Red and Blue.
3. Thresholds stay as written (quarantine at 3 contradictions in the last 8 outcomes; a re-probe of a quarantined entry every 200 steps).

## Required from User

Nothing before the run. Afterwards, not part of this directive (Claude does these on the laptop, where the ROM and the real memory are):

1. Perf-probe identity: run `tools/perf_probe.py` before and after the merge from the same state, compare the decision logs, and confirm `brain grades` reports `distrusted_state_flags` 0 on the probe's memory; then the decisions must match byte for byte.
2. Seeded-memory hands-off run: seed a memory containing the tonight shape (the map 40 starter-ball entry typed `info` with `done` true), run Red hands-off from the start of the game with the starter-fix branch not merged, and confirm the run gets past Oak's lab with party greater than 0 and does not press B for thousands of steps.
3. Poisoned entry: deliberately poison one entry (a wrong warp destination and a wrong `info` type) and confirm each is quarantined within `QUARANTINE_X` uses, the run continues, `brain grades` lists them, and a later correct probe lets one recover.
4. Run the ROM-present checks including `tests/test_golden_red.py` before merge.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/MEMORY_FACTS.md)
- Read(src/pokeagent/cli_brain.py)
- Read(src/pokeagent/cli_brain_memory.py)
- Read(src/pokeagent/brain/audit.py)
- Read(src/pokeagent/brain/fileops.py)
- Read(src/pokeagent/explorer/loop_memory.py)
- Read(src/pokeagent/explorer/loop_veto.py)
- Read(src/pokeagent/explorer/interaction_policy.py)
- Read(src/pokeagent/explorer/retalk_veto.py)
- Read(src/pokeagent/explorer/interaction_record.py)
- Read(src/pokeagent/explorer/memory.py)
- Read(src/pokeagent/explorer/memory_warps.py)
- Read(src/pokeagent/explorer/trainer_ledger.py)
- Read(src/pokeagent/explorer/headless_loop.py)
- Read(src/pokeagent/explorer/jsonl_buf.py)
- Read(tools/perf_probe.py)
- Read(tests/test_explorer_behaviours.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(uv run pokeagent brain grades --help)
- Exec(git diff)
- Exec(git ls-files)
- Exec(wc -l)

<!-- queue:start -->

## Queue

| Field | Value |
|---|---|
| Status | Draft |
| Assigned to | devin |
| Depends on | Memory_Audit_And_Fact_Labels_Directive.md |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-11 21:30 · claude · none → Draft — Drafted for Robert (approved 2026-11-11 ~21:15: "can it start self-grading memories?"): per-entry evidence sidecar, grades, hooks on loop ledger / talk outcome / warp taken, `brain grades`
<!-- queue:end -->
