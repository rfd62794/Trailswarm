# PokeAgent: Go-Explore slice 1 (cell census) - the cell key (`goexplore/cell.py`) and an offline census tool over existing run logs, no emulator

**Size:** S. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/go-explore-2026-11-14.md` (approved by Robert 2026-11-14; sections 2, 3 D2, 4 slice 1, 5). Base: current main. Slice 2 (`archive.py`, `select.py`, `store.py`) comes after this merges and imports `cell.py`.

## 1. Why this exists

Seed 12, heal_cerulean -> beat_misty, 12000 steps: 46% of steps went to training trips pinned to maps the agent never reached, beat_misty was not reached, SHAKE took 7.2% (`docs/plans/training-controller-2026-11-13.md` section 1). Go-Explore (plan above) fixes the structure: remember every distinct place the agent really stood, return to a good one exactly, spend a bounded budget from there. Everything rests on the **cell key** (plan D2): `(map_id, x // 4, y // 4, goals_reached_count, flag_popcount // 4, party_level_bucket)`. D2 names unknowns the plan says slice 1 must settle: how many cells a real run yields (estimate "a few hundred", unmeasured), whether a goals **count** is enough or a bitmask is needed (goals can be reached out of ladder order), and how noisy the flag popcount is. This slice builds the key as a pure function and a census tool that counts cells from run logs. **You** build and test it on tiny synthetic logs; **Claude** runs the real census on the laptop's run dirs afterwards (your worktree has no `runs/` and no ROM; both are gitignored).

### What the existing run logs actually contain (read from the writers, 2026-11-14)

`runs/explore-<date>-<time>-<pid>/decisions.jsonl` (writer `src/pokeagent/explorer/decisions.py`; the record builder is):

```python
FIELDS = ("step", "behaviour", "rule", "button", "map", "x", "y", "goal_stage", "box", "battle", "outcome", "reversal")   # decisions.py:15

def goal_stage(goals: dict) -> str:   # decisions.py:18-20
    """The first goal not yet reached (the stage the explorer is working on), or "done"."""
    return next((g for g in GOALS if not goals.get(g)), "done")

def make_record(step, behaviour, rule, button, before: tuple, stage, box, battle, outcome, reversal=False) -> dict:   # decisions.py:35-38
    return {"step": step, "behaviour": behaviour, "rule": rule, "button": button, "map": before[0], "x": before[1],
            "y": before[2], "goal_stage": stage, "box": box, "battle": battle, "outcome": outcome, "reversal": reversal}
```
`before` is `(map_id, x, y)`: the tile the decision was made on. Other rows in the same file carry an `"event"` key (`{"event": "heal_walk_start", ...}`, `{**rec, "event": "item_tossed"}` at `engine.py:100`): **skip every row with an `"event"` key**. The last line may be truncated (buffered writer, `jsonl_buf.py`): skip lines that are not valid JSON objects.

`goal_frames.jsonl` (writer `press_goals.py:67`): one line per goal first reached in that run: a JSON object with keys goal (e.g. left_house), step (e.g. 41) and frame (e.g. 9000), plus skipped = true for a settled-by-skip goal. `press_stop.py:42` also writes rows whose goal is like map:0x42 (a segment-stop marker, not a ladder goal: ignore any goal not in `GOALS`).

`transitions.jsonl` (`press.py:124`) has `step, from, button, to, moved, textbox, text, facing, source`: positions only, nothing the census needs beyond decisions.jsonl.

**Verdict for the D2 fields (do not invent data):**

| D2 field | in the logs? | source in the census |
|---|---|---|
| map_id, x, y | yes: `map`, `x`, `y` of each press row | the row |
| goals_reached_count | yes, indirectly: `goal_stage` is the first unreached ladder goal, so count = its index in `GOALS` (`"done"` = `len(GOALS)`; an unknown stage name = skip the row and count it) | `goals_reached(stage)` |
| flag_popcount // 4 | **NO.** Event flags are in RAM only (`read_snapshot`, `novelty/features.py:32`); no log carries them, and the state fingerprint does not store them (`statefp.fingerprint`, `statefp.py:28`) | `None`, reported as `not in logs` |
| party_level_bucket | **NO.** Party levels are in RAM; decisions.jsonl rows have none (only sparse `trainee_fainted` event rows) | `None`, reported as `not in logs` |

So the log census measures the position x goals part of the key only. The live key (`from_snapshot`) takes all six fields from one `Snapshot`; the flag and level fields get their real measurement in slice 3 (harvest) and slice 5. Say this plainly in the tool output.

## 2. Scope (files, in order)

1. `src/pokeagent/goexplore/__init__.py` (one-line docstring)
2. `src/pokeagent/goexplore/cell.py` (< 120 lines)
3. `tests/test_goexplore_cell.py`
4. `src/pokeagent/goexplore/census.py` (< 120 lines; the logic, importable)
5. `tools/cell_census.py` (< 60 lines; argparse wrapper)
6. `tests/test_goexplore_census.py`

Touch nothing else.

## 3. The work

### Real code shapes you build on (verified on main, 2026-11-14)

`src/pokeagent/novelty/features.py:20-29` (the Snapshot; do not edit this file):
```python
@dataclass(frozen=True)
class Snapshot:
    map: int = 0
    x: int = 0
    y: int = 0
    flags: bytes = b""       # 320 bytes from FLAGS_ADDR 0xD747 (FLAGS_ADDR, FLAGS_LEN = 0xD747, 320 at :11)
    bag: tuple = ()          # ((item id, qty), ...)
    pc: tuple = ()
    money: int = 0
    party: tuple = ()        # ((species, level, exp, moves, ident), ...)  -> level is party[i][1]
    in_battle: bool = False
    enemy: int = 0
    hp: int = 0
```
`from pokeagent.goals import GOALS` is the ordered ladder (a `list[str]`, 131 entries today; `goals.py:20`). Stage names in `decisions.jsonl` come from `GOALS` or `"done"`.

Good JSONL reader to reuse: `from pokeagent.review.load import jsonl` (`review/load.py:18`): `jsonl(path, skipped: dict | None = None) -> list[dict]` returns every valid JSON-object line of `path` (empty list when the file is missing; corrupt lines are counted in `skipped[path.name]`).

### 3.1 `src/pokeagent/goexplore/cell.py`

```python
BLOCK = 4          # tile block edge
FLAG_BUCKET = 4    # popcount // 4
LEVEL_BUCKET = 5   # max party level // 5

class Cell(NamedTuple):
    map_id: int
    bx: int                  # x // BLOCK
    by: int                  # y // BLOCK
    goals: int               # goals_reached_count (ladder prefix length)
    flag4: int | None        # flag_popcount // FLAG_BUCKET; None when unknown (logs)
    lvl5: int | None         # max party level // LEVEL_BUCKET; None when unknown
    party_n: int | None      # party size; None when unknown

def flag_popcount(flags: bytes) -> int                      # sum(b.bit_count() for b in flags)
def party_bucket(party: tuple) -> tuple[int, int]           # (max level // 5, len(party)); an empty party -> (0, 0)
def goals_reached(stage: str) -> int | None                 # GOALS.index(stage); "done" -> len(GOALS); anything else None
def from_snapshot(s: Snapshot, goals: int) -> Cell          # all six fields from one Snapshot
def from_log_row(row: dict, goals: int) -> Cell             # flag4 = lvl5 = party_n = None
def cell_id(c: Cell) -> str                                 # "12.2.1.7.5.3.2"; None written as "-"
def parse_id(s: str) -> Cell                                # exact inverse of cell_id ("-" -> None)
```
`from_snapshot` reads `s.map`, `s.x`, `s.y`, `s.flags`, `s.party` only. Integer floor division (`//`). `goals` is passed in because a Snapshot does not know the ladder; the caller (slice 3/4) takes it from `ctx.goal_steps`/`goals.json`. `cell_id` must be filesystem-safe (slice 2 uses it as a file name `cells/<id>.state`).

### 3.2 `src/pokeagent/goexplore/census.py`

```python
def press_rows(run_dir: Path, skipped: dict | None = None) -> list[dict]
    # decisions.jsonl rows with NO "event" key and int map/x/y and a str goal_stage; others dropped (count in skipped["bad_rows"]).
def census(run_dirs: list[Path]) -> dict
```
`census` returns a JSON-serialisable dict with exactly these keys:
- `runs` (dirs with at least one usable row), `rows` (usable rows), `skipped_rows` (event rows are NOT counted as skipped; rows with missing fields or an unknown stage are).
- `cells`: distinct `Cell`s over all runs, via `from_log_row(row, goals_reached(row["goal_stage"]))`.
- `cells_per_run`: `{run_dir.name: distinct cells}`.
- `cells_by_goals`: `{goals_count_as_str: distinct cells}`.
- `block_sweep`: `{"1": n, "2": n, "4": n, "8": n}`, distinct `(map, x // b, y // b, goals)` over all runs for each block edge `b`; must be non-decreasing as the block shrinks (a test asserts it).
- `monotone_violations`: `{run_name: n}` only for runs with n > 0, where n counts consecutive usable rows whose goals count DEcreased (stage regressed). Expected 0 everywhere; it is the "monotone goals count" check.
- `out_of_order_goals`: `{run_name: [goal, ...]}` only for runs where `goal_frames.jsonl` lists a ladder goal whose `GOALS` index is lower than that of a goal logged before it (skip `"skipped": true` lines and goals not in `GOALS`). This is the evidence for the D2 unknown "is a count enough or is a bitmask needed": a non-empty result means goals are reached out of ladder order.
- `not_in_logs`: always `["flag_popcount", "party_level_bucket"]`.

### 3.3 `tools/cell_census.py`

`uv run python tools/cell_census.py RUN_DIR [RUN_DIR ...] [--json]`. A run dir that does not exist is reported on stderr and skipped (exit 0 if at least one dir was readable, else exit 2). Prints a short table (cells, cells per run, cells by goals count, block sweep, monotone violations, out-of-order goals) then the line `flag_popcount and party_level_bucket: not in logs (measure live, slice 3)`. `--json` prints the dict. A `main(argv: list[str] | None = None) -> int` function, `if __name__ == "__main__": sys.exit(main())`. No `sys.path` tricks: `pokeagent` is installed in the venv.

### 3.4 Tests (all synthetic, `tmp_path`; no ROM, no `runs/`)

`tests/test_goexplore_cell.py`:
- `test_block_bucketing`: x/y 0..3 -> block 0, 4 -> 1, 7 -> 1, 8 -> 2; a tile pair in one block is the same cell, tiles across the edge are different cells.
- `test_flag_bucket_edges`: popcount 3 -> 0, 4 -> 1; `flag_popcount(bytes([0xFF, 0x01]))` == 9; a Snapshot with `flags=bytes([0b1111]) + bytes(319)` gives `flag4 == 1`; one flag bit set gives `flag4 == 0` (one story flag does not split a cell).
- `test_party_level_bucket`: levels (4,) -> (0,1); (5,) -> (1,1); (16, 8) -> (3,2); `()` -> (0,0). Build the party as `((species, level, exp, moves, ident), ...)` tuples.
- `test_goals_count_is_monotone_along_the_ladder`: for `i, g in enumerate(GOALS)`: `goals_reached(g) == i`; `goals_reached("done") == len(GOALS)`; `goals_reached("not_a_goal") is None`; the sequence over `GOALS + ["done"]` is strictly increasing.
- `test_from_snapshot_and_from_log_row`: a Snapshot(map=12, x=9, y=5, flags=..., party=...) -> the expected Cell; `from_log_row({"map": 12, "x": 9, "y": 5}, 7)` -> `Cell(12, 2, 1, 7, None, None, None)`.
- `test_cell_id_round_trip_with_none_fields`: `parse_id(cell_id(c)) == c` for a full cell and a log cell; the id has no path separator or colon.

`tests/test_goexplore_census.py` (build rows with the real `pokeagent.explorer.decisions.make_record`, write with `json.dumps` one per line):
- two fake run dirs; run A walks 6 tiles across two blocks while the stage goes `potion` -> `left_house` (ordered); assert the exact `cells`, `cells_per_run`, `cells_by_goals`, `monotone_violations == {}`.
- run B has stage regress (`left_house` then `potion`): `monotone_violations == {"<run B name>": 1}`.
- `block_sweep` non-decreasing as block shrinks (`n8 <= n4 <= n2 <= n1`).
- an `"event"` row, a corrupt line and a row with an unknown `goal_stage` are tolerated: usable `rows` and `skipped_rows` as expected.
- `goal_frames.jsonl` with `left_house` logged before `potion` -> `out_of_order_goals` names that run; an ordered file -> `{}`; a `"skipped": true` line and a `map:0x42` goal are ignored.
- empty dir / missing `decisions.jsonl` -> that run is not counted, no exception.
- `tools/cell_census.py` loaded with `importlib.util.spec_from_file_location` (the `_tool` helper pattern at `tests/test_novelty.py:33-39`) and `main([str(dirA), "--json"])` prints parseable JSON with `not_in_logs`; a nonexistent dir only -> returns 2.

## 4. What NOT to do

- No emulator, no `tools/explore_demo.py`, no ROM, no `runs/` access (it is absent; do not look for it). Never import `PyBoyEmulator`.
- Do not edit `novelty/features.py`, `statefp.py`, `goals.py`, `decisions.py`, or anything under `explorer/` (in particular no lines in `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`; nothing wired into `explorer/engine.py`).
- No archive, selection, store or driver code (slices 2-4). No new dependency.
- Do not guess flag or party data from the logs; they are `None`.
- Do not make up real-run numbers or hard-code expected real counts in tests.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

**Baseline first** (run on the unmodified base). Claude ran it on 2026-11-14 on current main: `36 passed, 1 warning in 1.17s`.
```
uv run pytest -q -p no:cacheprovider tests/test_novelty*.py
```
Expected: 0 failed. If not 0 failed, stop and write the failing ids in the Status row; do not fix them.

New tests:
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_cell.py tests/test_goexplore_census.py
```
Expected: all pass, none skipped.

```
wc -l src/pokeagent/goexplore/cell.py src/pokeagent/goexplore/census.py tools/cell_census.py
```
Expected: `cell.py` and `census.py` each < 120, `tools/cell_census.py` < 60.

```
uv run python tools/cell_census.py tests/does_not_exist
```
Expected: a "not found" message on stderr and exit code 2 (no traceback).

```
git diff --stat origin/main
git status --short
```
Expected: only the six files of section 2.

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (base count plus your new tests; skip count unchanged from the base). Record the base count first if you can.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the working directory. Do not search, glob or hunt for missing things: if something named here is missing, stop and write why in the Status row.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Create no scratch or debug files; if you need one, put it under `.devin-scratch/` and leave it there (deleting is denied).
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/goexplore-slice1-census`; commit as you go and push the branch.
- No ROM, no `runs/` access, no `tools/explore_demo.py`.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `goexplore/cell.py` exists with the signatures above, pure, < 120 lines. <!-- test: tests/test_goexplore_cell.py -->
- [ ] Bucketing (4x4 block, popcount // 4, (max level // 5, size)) is exact at the edges. <!-- test: tests/test_goexplore_cell.py::test_block_bucketing -->
- [ ] The goals count is monotone along the ladder. <!-- test: tests/test_goexplore_cell.py::test_goals_count_is_monotone_along_the_ladder -->
- [ ] `census.py` + `tools/cell_census.py` report the dict/table of 3.2-3.3 from synthetic logs, tolerate event rows, corrupt lines and missing files, and say flag popcount and party level are not in logs. <!-- test: tests/test_goexplore_census.py -->
- [ ] No file outside section 2 changed; no wiring into the explorer.
- [ ] Baseline gate, new tests and the full suite: 0 failed.

## 8. Report

Findings first: the six files with exact `wc -l`, any deviation from the signatures and why. Then the real output tails: baseline gate, new tests, the not-found tool run (exit code 2), the full-suite line. State plainly that no ROM and no real run data were used: the real census (`uv run python tools/cell_census.py runs/explore-*` on the laptop; cells per run for seeds 12 and 13, the block sweep, monotone violations, out-of-order goals) is Claude's after merge, and the flag-popcount / party-level fields stay unmeasured until slice 3.

## Required from User

Nothing for the build. After merge, Claude runs the real census on the laptop's run dirs and records the numbers against plan D2.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/go-explore-2026-11-14.md)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(uv run python tools/cell_census.py)
- Exec(git diff)
- Exec(git status)
- Exec(wc -l)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-goexplore-slice1-cell-census-directive |
| Base branch | - |
| Base commit | 776ccd7edcf5f35e1379906d2c097aaa268c4ebb |
| Head commit | c7298e6fff4f20b894bc6c6775adf577e2b693b3 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-13 23:43 · robert-claude-laptop · none → Queued — Robert approved Go-Explore doc (#246) and recs 2026-11-14.
- 2026-11-13 23:49 · robert-claude-laptop · Queued → Approved — lint override: Every cited goexplore/*, tools/cell_census.py and tests/test_goexplore_* path is a new file this directive creates; `map/x/y` is prose for the three decisions.jsonl fields, not a path.
- 2026-11-13 23:50 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice1-cell-census-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7C68BFDF2S979P0QZB3BBWJ
- 2026-11-13 23:54 · dispatcher · launched pid=21288; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice1-cell-census-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (7 declared need(s); 1 external))
- 2026-11-14 00:01 · devin · In progress → Review — Six files, no signature deviations: src/pokeagent/goexplore/__init__.py (1), cell.py (69), census.py (98), tools/cell_census.py (56), tests/test_goexplore_cell.py, tests/test_goexplore_census.py. Notes: skipped_rows counts corrupt lines + missing-field rows + unknown-stage rows (event rows excluded), matching review/load.py's vocabulary; in --json mode the tool prints only the dict (stdout stays parseable, not_in_logs is a key) and the 'not in logs' line prints in table mode only. Output tails: baseline gate `uv run pytest -q -p no:cacheprovider tests/test_novelty*.py` -> 36 passed, 0 failed. New tests -> 10 passed, 0 skipped. `uv run python tools/cell_census.py tests/does_not_exist` -> stderr 'not found: tests\does_not_exist', exit 2, no traceback. Full suite `uv run pytest -q -p no:cacheprovider` -> 2826 passed, 55 skipped, 0 failed (base 2871 items + 10 new; skips unchanged). One observation: an earlier full-suite pass on the unmodified base showed a single failure in tests/test_segment_curriculum.py::test_stray_bike_shop_checkpoint_does_not_become_the_frontier (seg_sched checkpoint validity); it passed run alone (30s) and passed in the final full run - a pre-existing order-dependent flake on base, untouched by this slice (all six files are new). `git diff --stat origin/main` also shows pre-existing branch divergence from the queue/dispatcher commits plus newer main work; nothing outside the six files was touched by me. No ROM, no runs/, no emulator used; all tests synthetic on tmp_path via the real decisions.make_record. The real census (uv run python tools/cell_census.py runs/explore-* on the laptop; cells per run for seeds 12 and 13, block sweep, monotone violations, out-of-order goals) is Claude's after merge; flag_popcount and party_level_bucket stay unmeasured until slice 3 harvest. [origin] spent: devin 7 min est. n/a
<!-- queue:end -->
