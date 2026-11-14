# PokeAgent: Go-Explore slice 4 (return and explore) - pick a cell with select.py, load its state, run N steps with the harvester attached, repeat; one small runner module and one tool

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/go-explore-2026-11-14.md` (approved by Robert 2026-11-14; sections 3 D1/D3/D5/D6/D8, 4 slice 4, 5). **Depends on:** slices 1 and 2 (merged: `goexplore/cell.py`, `archive.py`, `select.py`, `store.py`, `census.py`) and **slice 3 = PR #264** (`src/pokeagent/goexplore/cell_dump.py` and the `--cell-dump` flag in `tools/explore_demo.py`), which is NOT merged as of writing. **If `src/pokeagent/goexplore/cell_dump.py` is absent in your worktree, or `tools/explore_demo.py` has no `--cell-dump` flag, stop immediately and write "slice 3 (#264) not merged" in the Status row.** Do not recreate or copy it. Base: main containing #264.

The plan's slice 4 reads: "**Driver + runner.** `tools/go_explore.py`, `runner.py`, `budget.py`. One real smoke return of `--steps 50` (the only ROM use in this slice, on the laptop)." This directive builds that slice with `budget.py` folded into `runner.py` (the budget is one constant and one flag; a module for it would be under 10 lines). The real smoke return is the controller's, after review (section 5).

## 1. Why this exists

After slice 3 the explorer can write cells into an archive, but nothing returns to one. Go-Explore (plan section 1) is the loop: remember every distinct place the agent has really been, go back to a good one exactly, spend a bounded budget exploring from there. A bad branch costs one budget, not the rest of the run (seed 12, heal_cerulean -> beat_misty: 46% of 12000 steps went to training trips the agent never reached; the plan's evidence).

Two facts from the merged slice 3 code (read `src/pokeagent/goexplore/cell_dump.py` in your worktree; these are quoted from it on 2026-11-14) shape this slice:

1. **The archive is loaded ONCE per Harvester** (`self.archive = store.load(self.root)` in `Harvester.__init__`) and the Harvester then saves the WHOLE archive after every new or better cell (`store.save(self.archive, self.root)`). So two processes on one archive root would overwrite each other's cells, and the driver must never save the archive while a run is in flight. Runs on one archive root are strictly serialised, and the driver's only archive write (`mark_seen`) happens BEFORE it launches a run.
2. **The Harvester takes `parent` and `steps_offset`** (`Harvester.__init__(ctx, root, every, steps_offset=0, parent=None)`; `attach(ctx, engine, root, every, **kw)` forwards `**kw`) but `tools/explore_demo.py` passes neither today: its only call is `attach(ctx, engine, a.cell_dump)` (line 192 on the #264 branch). `_parent_for` only uses the return cell as a parent while it is still IN the archive (a dangling parent could close a cycle and break eviction), so the return cell must be in the archive when the run starts.

## 2. Scope (files, in order)

1. `src/pokeagent/goexplore/runner.py` (< 120 lines) + `tests/test_goexplore_runner.py`
2. `tools/go_explore.py` (< 80 lines) + `tests/test_go_explore_tool.py`
3. `tools/explore_demo.py`: exactly **+2 lines**: two `ap.add_argument(...)` lines (`--cell-from`, `--cell-steps`), and the existing `attach(...)` call (line 192 on the #264 branch) edited IN PLACE to forward them (0 net lines). Final `wc -l` must be <= 396 (it is 394 on the #264 branch; the file is already over the 300-line rule, so do not reformat, move or trim anything in it).

Touch nothing else.

## 3. The work

### Real code shapes you build on (verified on the #264 branch, 2026-11-14)

`goexplore/select.py`:
```python
def choose(archive: Archive, rng: random.Random, on_route: frozenset[str] = frozenset()) -> str | None   # weighted draw, None when empty; never mutates the archive or touches global random
```
`goexplore/archive.py`: `Archive.entries: dict[str, Entry]`, `Archive.mark_seen(cid)` (n_seen += 1, unknown cid ignored), `Entry(cid, state, goals, steps, hp, n_seen, novelty, parent, lineage)`; `Entry.state` is relative to the archive root, always `cells/<cid>.state` with forward slashes.
`goexplore/store.py`: `load(root) -> Archive` (empty if no `archive.json`; `ValueError` if present but bad), `save(archive, root)` (atomic).
`statefp.lineage(Path) -> str` (`organic` / `synthetic` / `promoted`; a missing sidecar reads `organic`); `statefp.write(state, dict)` writes a sidecar (tests use it to make a synthetic one: `statefp.write(state, {"v": 1, "lineage": "synthetic"})`).

The `explore_demo.py` flags the driver uses (all exist on main, verified): `--state PATH`, `--steps N`, `--headless`, `--seed N`, `--stop-at-goal GOAL` (choices from `pokeagent.goals.GOALS`), and (from #264) `--cell-dump DIR`. The process exits 0 after `--steps` presses or when `--stop-at-goal` lands. Each process creates its own `runs/explore-<time>-<pid>/` run dir (unique, nothing to clean up). A loaded state restores the emulator, not the explorer: `ctx` and `MapMemory` start cold on every return (plan section 2, "Surprise"; plan D1 accepts this), so each return is a fresh process.

### 3.1 `tools/explore_demo.py` (+2 lines)

Add, next to the `--cell-dump` flag:
```python
ap.add_argument("--cell-from", default=None, help="cid of the archived cell this run returned from (slice 4; the harvester parent)")
ap.add_argument("--cell-steps", type=int, default=0, help="emulator steps already spent reaching that cell (slice 4; harvester steps_offset)")
```
and change the existing `attach` call to `attach(ctx, engine, a.cell_dump, parent=a.cell_from, steps_offset=a.cell_steps)` (keep it inside the existing `if a.cell_dump:` block, same line). Defaults (`None`, `0`) equal the Harvester's own defaults, so a run without the new flags behaves exactly as under #264.

### 3.2 `goexplore/runner.py` (< 120 lines)

```python
DEFAULT_STEPS = 600          # plan D6: steps per return (a flag on the tool)
LINEAGES_OK = ("organic", "promoted")   # plan D8: the driver refuses to start from anything else

@dataclass(frozen=True)
class Return:
    index: int
    cid: str | None          # the archived cell returned to; None for the first run from the start state
    state: Path              # the state file handed to explore_demo --state
    steps_offset: int        # Entry.steps of the cell (0 for the start state)
    seed: int                # base_seed + index (plan D1 mitigation: a cell is not replayed identically)

def pick(root: Path, start_state: Path, index: int, base_seed: int, commit: bool = True) -> Return
def command(r: Return, root: Path, steps: int = DEFAULT_STEPS, stop_goal: str | None = None, python: str = sys.executable) -> list[str]
def drive(root, start_state, returns, steps=DEFAULT_STEPS, base_seed=0, stop_goal=None, run=subprocess.run) -> list[int]
```
Behaviour:
- `pick`: `archive = store.load(root)`. If the archive is EMPTY, return `Return(index, None, start_state, 0, base_seed + index)`. Otherwise `cid = select.choose(archive, random.Random(base_seed + index))` (no `on_route`: the plan has no planner here, pass nothing), `e = archive.entries[cid]` (the return cell MUST be in the archive: a `KeyError` here is a bug, let it raise), `state = root / e.state`. Refuse with `FileNotFoundError` if `state` is not a file, and with `ValueError` if `statefp.lineage(state)` (or, for the start state, `statefp.lineage(start_state)`) is not in `LINEAGES_OK` (plan D8). With `commit=True` call `archive.mark_seen(cid)` then `store.save(archive, root)`; with `commit=False` (dry run) write nothing.
- `command`: argv list `[python, "tools/explore_demo.py", "--headless", "--state", str(r.state), "--steps", str(steps), "--seed", str(r.seed), "--cell-dump", str(root)]`, plus `["--stop-at-goal", stop_goal]` when given, plus `["--cell-from", r.cid, "--cell-steps", str(r.steps_offset)]` when `r.cid` is not None. Strings only (no `Path` objects in argv).
- `drive`: acquire the single-driver lock first: `os.open(root / "driver.lock", O_CREAT | O_EXCL | O_WRONLY)` (create `root` if missing), write the pid, and in a `finally` `os.close` it and `Path.unlink(missing_ok=True)` it. A `FileExistsError` becomes `RuntimeError(f"another driver holds {lock}; if no driver is running, remove that file")`. Then for `i in range(returns)`: `r = pick(...)`; `code = run(command(r, root, steps, stop_goal), cwd=REPO_ROOT).returncode` (`REPO_ROOT = Path(__file__).resolve().parents[3]`, the same idiom `grind/measure.py:20` uses); print one line `return {i} cid={r.cid} offset={r.steps_offset} seed={r.seed} exit={code} cells={len(store.load(root))}` (the `store.load` after the run also proves the archive is still readable: a `ValueError` stops the driver, let it raise); append `code`; stop the loop at the first non-zero `code`. Return the list of exit codes. **The driver never calls `store.save` after a run launches** (see section 1, fact 1).
- Plan D8: the cell chain is the `Entry.parent` links the Harvester writes; this module adds no new chain format. Never edit a state file, never call an `edit_class` tool.

### 3.3 `tools/go_explore.py` (< 80 lines)

```
uv run python tools/go_explore.py --archive runs/goexplore/<run-id> --start-state <organic .state> [--returns 3] [--steps 600] [--seed 0] [--stop-at-goal GOAL] [--dry-run]
```
Thin argparse wrapper around `runner.drive`: `--archive` and `--start-state` required; `--returns` default 3; `--steps` default `runner.DEFAULT_STEPS`; `--seed` default 0; `--stop-at-goal` choices `pokeagent.goals.GOALS`. `--dry-run` calls `runner.pick(..., index=0, commit=False)` once and prints `" ".join(runner.command(...))` for the next return, touching no archive file and starting no process. `main(argv=None) -> int` returns 0 on success, 1 when any run exited non-zero, 2 on a refusal (`ValueError` / `FileNotFoundError` / `RuntimeError` printed to stderr, no traceback). Module docstring with the usage line. All logic stays in `runner.py`.

### 3.4 Tests (no emulator, no subprocess, `tmp_path` only)

`tests/test_goexplore_runner.py`. Build an archive with `store.save(Archive(), root)` after `archive.offer(Entry(cid, f"cells/{cid}.state", goals, steps))` (use cids like `"12.2.1.7.5.3.2"`) and write a dummy state file `root / "cells" / f"{cid}.state"` (any bytes). Pass a fake `run` callable that records the argv and `cwd` and returns `SimpleNamespace(returncode=0)`.

Required tests:
1. `test_empty_archive_starts_from_the_start_state`: index 0 returns `cid is None`, `state == start_state`, and `command(...)` has no `--cell-from`.
2. `test_pick_is_deterministic_and_returns_an_archived_cell`: same `(root, base_seed, index)` gives the same cid twice; `r.state` is inside `root / "cells"`; `r.steps_offset == entry.steps`; seed is `base_seed + index`.
3. `test_command_carries_parent_and_offset`: argv contains `--cell-dump <root>`, `--cell-from <cid>`, `--cell-steps <steps>`, `--headless`, `--steps 600` by default, `--stop-at-goal` only when given; every element is a `str`.
4. `test_mark_seen_is_saved_before_the_run_starts`: the fake `run` reads `archive.json` at call time and sees `n_seen == 1` for the picked cell. This pins "the driver's only archive write happens before launch".
5. `test_driver_does_not_write_the_archive_after_a_run`: the fake `run` rewrites `archive.json` (adding a second cell, as a Harvester would); after `drive(returns=1)` that second cell is still there (a driver that saved its stale copy would erase it).
6. `test_synthetic_state_is_refused`: a synthetic sidecar on the picked state (and, separately, on the start state) raises `ValueError`, and `run` is never called.
7. `test_missing_state_file_is_refused`: `FileNotFoundError`, `run` never called.
8. `test_nonzero_exit_stops_the_loop`: `returns=5`, the fake returns 1 on the second call: `drive` returns `[0, 1]` and `run` was called twice.
9. `test_second_driver_is_refused_and_lock_is_removed`: with `driver.lock` present `drive` raises `RuntimeError` and does not remove it; after a normal `drive` (and after a `run` that raises) no `driver.lock` remains.
10. `test_dry_run_changes_nothing`: `pick(..., commit=False)` leaves `archive.json` byte-identical.
11. `test_corrupt_archive_stops_the_driver`: an unreadable `archive.json` raises `ValueError` from `drive`.

`tests/test_go_explore_tool.py`: `main(["--archive", ..., "--start-state", ..., "--dry-run"])` returns 0, prints a line that contains `tools/explore_demo.py` and `--cell-dump`, and creates no `archive.json` and no `driver.lock`; a synthetic start state returns 2 and prints nothing to stdout.

## 4. What NOT to do

- No emulator process, no PyBoy, no ROM, no `runs/` access (absent in your worktree; do not look). **No real subprocess to `tools/explore_demo.py` in any test**: tests inject the fake `run`. The real smoke return is the controller's.
- Do not edit `cell.py`, `archive.py`, `select.py`, `store.py`, `census.py`, `cell_dump.py`, `statefp.py`, `emulator.py`, `novelty/*`. If something there looks wrong, report it, do not patch it.
- Add nothing to `tools/explore_demo.py` beyond the 2 lines and the in-place `attach` edit; no logic there. No lines in `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`; nothing in `explorer/engine.py`, `explorer/headless_loop.py`, `explorer/press*.py`, or the loop guard (`explorer/behaviours/guards.py`).
- Never run two returns at once, never use threads or a pool, never share an archive root between two drivers (plan D6: one emulator, sequential).
- Do not save or evict the archive from the driver after a run launches. Do not fill `Entry.novelty` (it stays 0.0; filling it from discoveries is a later slice, and the plan's slice list does not include it).
- No A/B, no seed 12/13 comparison, no new `docs/plans` note (slice 5). No state surgery, no `edit_class` edits, no new log files in the run dir, no new dependency, no `budget.py`.
- Never commit or push states, ROMs, or archives.

## 5. Verification (exact commands, from the worktree root)

Baseline first, on main containing #264 (Claude ran this on a worktree at the #264 head on 2026-11-14): `87 passed, 1 warning`.
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_*.py tests/test_novelty*.py
```
Expected: 0 failed. If not, stop and write the failing ids; do not fix them. (On main WITHOUT #264 the same command gives `74 passed`; if you see 74, slice 3 is not merged: stop.)

New tests:
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_runner.py tests/test_go_explore_tool.py
```
Expected: all pass, none skipped.
```
wc -l src/pokeagent/goexplore/runner.py tools/go_explore.py tools/explore_demo.py
git diff --stat origin/main
git diff origin/main -- tools/explore_demo.py
git grep -n "cell_from\|cell-from\|cell_steps\|cell-steps" -- src tools
```
Expected: `runner.py` < 120; `go_explore.py` < 80; `explore_demo.py` <= 396; the stat lists only `runner.py`, `go_explore.py`, the two tests and `tools/explore_demo.py` (2 insertions, 1 deletion plus 1 insertion for the edited `attach` line, i.e. `3 insertions(+), 1 deletion(-)` against the #264 base); the explore_demo diff shows exactly the two flag lines and the one edited call; the grep hits only `tools/explore_demo.py` and `goexplore/runner.py`.
(If main already contains #264 the diff against `origin/main` is only your change; if you diff against a base that does not, say so in the report.)

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`; takes about 3 minutes):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (main without #264 was `2951 passed, 63 skipped` on 2026-11-14; yours is that plus #264's tests plus your new ones; the skip count unchanged).

**Not yours (the controller, on the laptop, after review):** the real-ROM smoke. With an organic checkpoint as the start state: `uv run python tools/go_explore.py --archive runs/goexplore/smoke --start-state <organic .state> --returns 2 --steps 50 --seed 12`. Pass: exit 0; `archive.json` lists at least one cell; the second return's command line carries `--cell-from <a cid from the first return>`; its new cells have `parent` set; `uv run python tools/go_explore.py ... --dry-run` prints the same command shape; and a flag-off `tools/explore_demo.py --steps 300 --seed 12` `decisions.jsonl` is byte-identical to main. You cannot prove any of that; do not claim it.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the worktree. Do not search, glob or hunt for missing things: if something named here is missing, stop and write why in the Status row. Never use `python -c`.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Never delete files from the repo. Create no scratch or debug files (tests write only under `tmp_path`).
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/goexplore-slice4-return-and-explore`; commit as you go and push the branch.
- No ROM, no `runs/` access.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `runner.py` has `Return`, `pick`, `command`, `drive`, `DEFAULT_STEPS`, < 120 lines; `tools/go_explore.py` < 80 lines with `--dry-run`.
- [ ] `tools/explore_demo.py` grew by exactly 2 lines (<= 396 total); defaults of the new flags equal the Harvester's defaults.
- [ ] The driver serialises runs on one archive root and writes the archive only before launching a run. <!-- test: tests/test_goexplore_runner.py::test_mark_seen_is_saved_before_the_run_starts -->
- [ ] A run's return cell is archived and its state file exists; a synthetic start or cell is refused. <!-- test: tests/test_goexplore_runner.py::test_synthetic_state_is_refused -->
- [ ] A second driver on one root is refused; the lock is always released. <!-- test: tests/test_goexplore_runner.py::test_second_driver_is_refused_and_lock_is_removed -->
- [ ] A non-zero exit stops the loop. <!-- test: tests/test_goexplore_runner.py::test_nonzero_exit_stops_the_loop -->
- [ ] No file outside section 2 changed; nothing wired into `engine.py`.
- [ ] Baseline gate, new tests and the full suite: 0 failed.

## 8. Report

Findings first: `wc -l` of the three files, the exact explore_demo diff, any name that differed from the signatures above (the merged files win; report the difference), and anything in `cell_dump.py` that conflicted with section 1. Then the real output tails: baseline gate, new tests, the full-suite line. State plainly that no ROM and no subprocess was used and that the real smoke (`--returns 2 --steps 50`) and the flag-off byte-identical check are the controller's, run on the laptop after review.

## Required from User

Nothing for the build. Queue only after #264 (slice 3) has merged.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/go-explore-2026-11-14.md)
- Read(src/pokeagent/goexplore/cell_dump.py)
- Read(src/pokeagent/goexplore/archive.py)
- Read(src/pokeagent/goexplore/select.py)
- Read(src/pokeagent/goexplore/store.py)
- Read(src/pokeagent/statefp.py)
- Read(tools/explore_demo.py)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-goexplore-slice4-return-and-explo-ee9a20 |
| Base branch | - |
| Base commit | b20d4ce093988fd9b7bc31e0e7912df1b1e81a75 |

**Status log**
- 2026-11-14 09:00 · robert-claude-laptop · none → Queued
- 2026-11-14 09:01 · robert-claude-laptop · Queued → Approved — lint override: runner.py, go_explore.py and the two test files are NEW files this directive creates; goexplore/runner.py and grind/measure.py are src/pokeagent-relative names (src/pokeagent/grind/measure.py exists); the go_explore.py usage line is documentation of the tool being built, and section 4 forbids running any subprocess, ROM or runs/ access. Reviewed by Claude (controller) 2026-11-14.
- 2026-11-14 09:15 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice4-return-and-explo-ee9a20; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7D6K5DS38EYW4TCBBMHMWB8
- 2026-11-14 09:18 · dispatcher · launched pid=17708; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice4-return-and-explo-ee9a20; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (11 declared need(s); 7 external))
- 2026-11-14 11:52 · agentflow-tick · In progress → Blocked — host shutdown/reboot; last activity 2026-11-14T09:24:35, found gone at 2026-11-14T11:43:15 (boot 2026-11-14T11:41:42, trigger lock-takeover); wip commit failed; wip/pokeagent-goexplore-slice4-return-and-explo-ee9a20@9f8df9e pushed
- 2026-11-14 12:20 · robert-claude-laptop · Blocked → Queued — Run lost to a clean laptop power-off at 09:24 (Event 1074, Start menu); no branch pushed. Requeue unchanged.
- 2026-11-14 12:21 · robert-claude-laptop · Queued → Approved — lint override: Same as the 09:01 override (re-approve after power-off lost the run): runner.py, go_explore.py and the two test files are NEW files this directive creates; goexplore/runner.py and grind/measure.py are src/pokeagent-relative (src/pokeagent/grind/measure.py re-verified present 12:2x); the go_explore.py usage line documents the tool being built.
- 2026-11-14 12:54 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-goexplore-slice4-return-and-explo-ee9a20; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7DK4KFM8PNHBNE88G4C84NW
<!-- queue:end -->
