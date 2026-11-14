# PokeAgent: Go-Explore slice 5 (A/B report) - one small report module and tool that turn plain-vs-Go-Explore run dirs into the plan's D7 numbers table; the real-ROM A/B itself is the controller's

**Size:** S. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/go-explore-2026-11-14.md` (approved by Robert 2026-11-14; sections 3 D7, D8, 4 slice 5, 5). **Depends on slice 4 (return and explore)**, which is directive `docs/directives/GoExplore_Slice4_Return_And_Explore_Directive.md`: it adds `src/pokeagent/goexplore/runner.py` and `tools/go_explore.py`. **If `src/pokeagent/goexplore/runner.py` is absent in your worktree, or `tools/go_explore.py` is absent, stop immediately and write "slice 4 not merged" in the Status row.** Do not recreate either. Already merged: slices 1 to 3 (`src/pokeagent/goexplore/{cell,archive,select,store,census,cell_dump}.py`, `tools/cell_census.py`). Base: current main containing slice 4.

The plan's slice 5 reads: "**A/B (D7)** on seeds 12 and 13; results go in a dated note under `docs/plans/`." and, under it: "Slice 5 needs Robert's read of the numbers." D7 defines the A/B: seed 12 and seed 13, same stage (heal_cerulean -> beat_misty), equal total emulator steps (12000: plain `tools/explore_demo.py` vs Go-Explore, returns summed), one run per arm per seed, with metrics (1) distinct cells, (2) milestone reached, (3) steps-to-milestone, (4) novelty discoveries per 1k steps, (5) SHAKE share and blackouts.

**That slice is a real-ROM measurement with no code of its own, so it is not a directive for Devin.** The controller runs it on the laptop (section 5). This directive builds the smallest code the A/B needs: a report that reads the two arms' run dirs (and the Go-Explore archive) and prints the D7 table, so the dated note is a paste, not hand arithmetic. Devin never touches a ROM, a run, or `runs/`.

## 1. Why this exists

Today the D7 numbers would be assembled by hand from five tools: `src/pokeagent/goexplore/census.py` (cells), `src/pokeagent/evaluation_ab.py` (`extract_metrics`: solved, steps, blackouts, presses), the SHAKE rows in `decisions.jsonl`, and the archive. Two traps make hand assembly wrong, and this directive exists to remove them:

1. **Apples to apples on cells.** The plain arm only has run logs, and a log row carries (map, x, y, goal stage): the census key is `(map, x // 4, y // 4, goals_reached)`. The archive's live key also has flag popcount and party level, which a plain run's logs do not have. So the comparable "distinct cells" figure is the LOG census over each arm's run dirs (`src/pokeagent/goexplore/census.py` `census(run_dirs)["cells"]`, which already unions across dirs). The archive's own cell count is a separate, Go-Explore-only row and must not be compared to the plain arm.
2. **Steps-to-milestone across returns.** In the Go-Explore arm each return is its own run dir with its own step counter. A milestone hit at step 400 of the third return is not "400 steps": it is (presses of the earlier returns) + 400. Run dirs are named `explore-<YYYYMMDD>-<HHMMSS>-<pid>` so sorting by name is chronological.

Verified on current main (2026-11-14), these pieces compose as the work below assumes (a throwaway probe, not committed): for a run dir with 10 press rows and one `goal_frames.jsonl` row `{"goal": "left_house", "step": 7, "frame": 70}`, `extract_metrics(dir, "left_house")` returned `{'solved': True, 'steps': 7, 'frames': 70, 'presses': 10, 'cap': None, 'stalls': 0, 'blackouts': 0, 'battles': 0, 'item_tossed': 0}` and `census([dir])` returned `cells: 3, rows: 10, runs: 1`. A SHAKE press row has `rule == "shake_walk"` (`src/pokeagent/explorer/behaviours/guards.py:54`; `decisions.jsonl` rows are made by `make_record` in `src/pokeagent/explorer/decisions.py`).

## 2. Scope (files, in order)

1. `src/pokeagent/goexplore/report.py` (< 120 lines) + `tests/test_goexplore_report.py`
2. `tools/go_explore_report.py` (< 80 lines) + `tests/test_go_explore_report_tool.py`

Touch nothing else.

## 3. The work

### Real code shapes you build on (verified on main, 2026-11-14)

```python
# src/pokeagent/evaluation_ab.py
def extract_metrics(run_dir: Path | str, goal: str, cap: int | None = None) -> dict
#   keys: solved, steps (None when unsolved), frames, presses, cap, stalls, blackouts, battles, item_tossed
# src/pokeagent/goexplore/census.py
def census(run_dirs: list[Path]) -> dict                      # keys incl. "cells", "runs", "rows", "cells_per_run"; dirs with no usable press row are skipped, never an error
def press_rows(run_dir: Path, skipped: dict | None = None) -> list[dict]   # decisions.jsonl press rows only (no "event" key)
# src/pokeagent/goexplore/store.py
def load(root: Path) -> Archive                                # empty Archive when no archive.json; ValueError when present but bad
# src/pokeagent/goexplore/archive.py
Archive.entries: dict[str, Entry]; Entry(cid, state, goals, steps, hp, n_seen, novelty, parent, lineage)
# src/pokeagent/goals.py
GOALS: the ordered ladder (a tuple of goal names; "potion", "left_house", "first_pokemon", ...)
```

### 3.1 `src/pokeagent/goexplore/report.py` (< 120 lines)

```python
EQUAL_STEPS_TOLERANCE = 0.02     # the arms count as "equal total steps" when presses differ by <= 2% (plan D7)
LINEAGES_OK = ("organic", "promoted")   # plan D8; the same pair src/pokeagent/goexplore/runner.py uses

def arm(run_dirs: list[Path], goal: str) -> dict
def archive_facts(root: Path) -> dict
def compare(plain: dict, go: dict) -> dict
def render(plain: dict, go: dict, cmp: dict, facts: dict | None = None) -> str
```

- `arm(run_dirs, goal)`: sort `run_dirs` by `Path.name`. For each, `m = extract_metrics(d, goal)` and `shake = sum(1 for r in press_rows(d) if r.get("rule") == "shake_walk")`. Return a dict with exactly these keys:
  - `runs`: number of dirs given; `presses`: `sum(m["presses"])`; `cells`: `census(dirs)["cells"]` (ONE call over all of the arm's dirs, so the count is the union); `cells_per_run`: `census(dirs)["cells_per_run"]`.
  - `milestone`: True when any run has `m["solved"]`; `steps_to_milestone`: for the FIRST solved run in sorted order, `(sum of m["presses"] of the runs before it) + m["steps"]`, else `None`.
  - `blackouts`: `sum(m["blackouts"])`; `shake_share`: `sum(shake) / presses` (0.0 when `presses == 0`).
  - `per_run`: list of `{"run": d.name, "presses": m["presses"], "solved": m["solved"], "steps": m["steps"], "blackouts": m["blackouts"], "shake": shake}`.
  - A dir with no `decisions.jsonl` counts as 0 presses and is not an error (`extract_metrics` already tolerates it). An empty `run_dirs` list returns the same dict with zeros / `None` / `False`.
- `archive_facts(root)`: `a = store.load(root)` (let `ValueError` propagate: a corrupt archive must stop the report). Return `{"cells": len(a), "by_goals": {str(g): count of entries with that goals value, sorted by int(g)}, "max_goals": max goals or 0, "max_chain": the longest parent chain length, "non_organic": sorted cids whose lineage is not in LINEAGES_OK}`. `max_chain`: for each entry follow `.parent` while the parent cid is in `a.entries`, counting links, with a visited-set so a cycle ends the walk (never loops forever); the entry alone is chain 1. An empty archive gives `max_chain 0`. This is plan D8's "cell chain" made visible: the controller reads it before a milestone counts.
- `compare(plain, go)`: pure arithmetic on two `arm` dicts. Return:
  ```
  {"steps": {"plain": p, "go": g, "ratio": g / p (None when p == 0), "comparable": ratio is not None and abs(ratio - 1) <= EQUAL_STEPS_TOLERANCE},
   "cells": {"plain": ..., "go": ..., "delta": go - plain, "more": go > plain},
   "milestone": {"plain": bool, "go": bool},
   "steps_to_milestone": {"plain": int | None, "go": int | None},
   "shake_share": {"plain": ..., "go": ..., "not_up": go <= plain},
   "blackouts": {"plain": ..., "go": ..., "not_up": go <= plain}}
  ```
  There is deliberately NO pass/fail field: plan D7's pass rule also needs "floor progress not worse" and Robert's read of the numbers, neither of which this report computes.
- `render(plain, go, cmp, facts=None)`: Markdown. One table `| Metric | Plain | Go-Explore |` with rows `runs`, `presses (total steps)`, `distinct cells (log census, comparable)`, `milestone reached`, `steps to milestone`, `blackouts`, `SHAKE share`; then a line `equal steps: <comparable> (ratio <x>)`; then, when `facts` is given, a short block `Go-Explore archive (full cell key, NOT comparable to the plain arm): cells N, max goals G, longest cell chain C, non-organic cells: [...]`; then a per-run table for each arm (`run | presses | solved | steps | blackouts | shake`); then the literal last line `No verdict: plan D7 also needs floor progress (tools/step_budget.py per run) and Robert's read.` Format `shake_share` as a percentage with one decimal and `ratio` with 3 decimals; render `None` as `-`.

### 3.2 `tools/go_explore_report.py` (< 80 lines)

```
uv run python tools/go_explore_report.py --goal beat_misty --plain RUN_DIR [RUN_DIR ...] --go RUN_DIR [RUN_DIR ...] [--archive runs/goexplore/<run-id>] [--json]
```
Thin argparse wrapper: `--goal` required, `choices=pokeagent.goals.GOALS`; `--plain` and `--go` required, `nargs="+"`, `type=Path`; `--archive` optional; `--json` prints `json.dumps({"plain": ..., "go": ..., "compare": ..., "archive": ...}, indent=1)` instead of Markdown. A run dir that is not a directory: print `not found: <dir>` to stderr and return 2 before computing anything. A `ValueError` from a corrupt archive: print it to stderr and return 2 (no traceback). Otherwise return 0. `main(argv=None) -> int`; module docstring with the usage line; all logic stays in `src/pokeagent/goexplore/report.py`.

### 3.3 Tests (`tmp_path` only; no emulator, no subprocess)

Helper in the test file: `_run(tmp_path, name, rows, frames=())` creates `tmp_path / name`, writes `decisions.jsonl` from `make_record(step, "b", rule, "UP", (map, x, y), GOALS[0], False, False, "moved")` rows and `goal_frames.jsonl` from `{"goal": g, "step": s, "frame": s * 10}` rows (import `make_record` from `pokeagent.explorer.decisions`, `GOALS` from `pokeagent.goals`). Use run names like `explore-20261114-100000-1` so sort order is the chronological order.

`tests/test_goexplore_report.py`, required:
1. `test_arm_counts_presses_shake_blackouts_and_cells`: two dirs; `presses` is the sum, `shake_share` is shake rows over presses, `cells` equals `census([both])["cells"]` (union, not the sum: give the dirs one shared tile).
2. `test_steps_to_milestone_adds_earlier_returns`: dir 1 has 100 press rows and no goal frame; dir 2 has a goal frame `{"goal": GOALS[1], "step": 40}`; `arm(..., GOALS[1])` gives `milestone True` and `steps_to_milestone == 140`. Dirs passed in REVERSE order still give 140 (sorted by name).
3. `test_unsolved_arm_has_none_steps_to_milestone`.
4. `test_missing_decisions_file_is_zero_presses_not_an_error`, and `test_empty_run_list_is_all_zero`.
5. `test_archive_facts_chain_and_non_organic`: build an archive with `store.save(Archive(), root)` after `archive.offer(Entry(cid, f"cells/{cid}.state", goals, steps, parent=...))` for a 3-link chain a <- b <- c plus one entry with `lineage="synthetic"`: `max_chain == 3`, `cells == 4`, `non_organic` lists exactly the synthetic cid, `by_goals` keys sorted as ints. A two-entry parent cycle (a.parent = b, b.parent = a, written by hand into the Entry objects before `store.save`) terminates and returns a finite `max_chain` (do not assert the exact value, only `<= 2`).
6. `test_archive_facts_empty_and_corrupt`: no `archive.json` gives `cells 0, max_chain 0`; a garbage `archive.json` raises `ValueError`.
7. `test_compare_flags`: equal presses give `comparable True`; 5% apart gives False; `p == 0` gives `ratio None` and `comparable False`; `cells.more`, `shake_share.not_up`, `blackouts.not_up` flip correctly on a hand-made pair of dicts (equal shake share counts as `not_up True`).
8. `test_render_has_the_no_verdict_line_and_dashes_for_none`.

`tests/test_go_explore_report_tool.py`: load the tool with `importlib.util.spec_from_file_location` exactly as `tests/test_goexplore_census.py` does (`_tool`). (1) `main(["--goal", GOALS[1], "--plain", d1, "--go", d2])` returns 0 and stdout contains `distinct cells`; (2) with `--json` stdout parses as JSON with keys `plain`, `go`, `compare`; (3) a missing dir returns 2 and writes `not found` to stderr only; (4) a corrupt `--archive` returns 2 with nothing on stdout.

## 4. What NOT to do

- No emulator, PyBoy, ROM or `runs/` access (absent in your worktree; do not look). **Run no `tools/explore_demo.py`, no `tools/go_explore.py`, no subprocess of any kind.** The real A/B is the controller's.
- Do not edit `src/pokeagent/goexplore/{cell,archive,select,store,census,cell_dump,runner}.py`, `src/pokeagent/evaluation_ab.py`, `tools/step_budget.py`, `tools/go_explore.py`, `tools/explore_demo.py`, `tools/cell_census.py`. If something there looks wrong, report it, do not patch it.
- Do not import from `tools/` inside `src/pokeagent/` (SHAKE share is computed here from `press_rows`, not by `tools/step_budget.py`).
- Do not compute novelty discoveries per 1k, floor progress, or a pass/fail verdict (open items for the controller, section 5). Do not write the dated note under `docs/plans/`: it needs the real numbers and Robert's read, and is the controller's. Do not add a `docs/plans` file at all.
- No new dependency; no new file outside section 2. Never commit or push states, ROMs, archives or run dirs.

## 5. Verification (exact commands, from the worktree root)

Baseline first. On main containing #264 but before slice 4, Claude ran this on 2026-11-14: `87 passed, 1 warning in 3.42s`. With slice 4 merged the count is 87 plus slice 4's runner and tool tests; record the number you see before your first edit, and it must be the same after.
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_*.py tests/test_novelty*.py
```
Expected: 0 failed. If not, stop and write the failing ids; do not fix them.

New tests:
```
uv run pytest -q -p no:cacheprovider tests/test_goexplore_report.py tests/test_go_explore_report_tool.py
```
Expected: all pass, none skipped.
```
wc -l src/pokeagent/goexplore/report.py tools/go_explore_report.py
git diff --stat origin/main
```
Expected: `src/pokeagent/goexplore/report.py` < 120, `tools/go_explore_report.py` < 80, the stat lists only the four files of section 2.

Full suite, once, at the end (pytest-xdist is NOT installed; never use `-n`; about 3 minutes):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed (main before slice 4 was `2951 passed, 63 skipped` on 2026-11-14; yours is that plus later merges plus your new tests; skip count unchanged).

**Not yours (the controller, on the laptop, after review):** the real A/B per plan D7, then this report over its run dirs, then the dated note under `docs/plans/` for Robert. Per seed S in {12, 13}: plain arm `uv run python tools/explore_demo.py --headless --state <the organic heal_cerulean checkpoint> --steps 12000 --seed S --stop-at-goal beat_misty`; Go-Explore arm `uv run python tools/go_explore.py --archive runs/goexplore/ab-S --start-state <the same checkpoint> --returns 20 --steps 600 --seed S --stop-at-goal beat_misty` (20 x 600 = 12000 steps; one heavy job at a time); then `uv run python tools/go_explore_report.py --goal beat_misty --plain <plain run dir> --go <the 20 return run dirs, in order> --archive runs/goexplore/ab-S`. The controller also reads discoveries per 1k and the floor-progress row from `tools/step_budget.py` per run. You cannot do any of that; do not claim it.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch (pytest-xdist is NOT installed: never use `-n`). Never read outside the worktree. Do not search, glob or hunt for missing things: if something named here is missing, stop and write why in the Status row. Never use `python -c`.
- Use `uv run` and Python 3.12 only; no bare `python`.
- Never delete files from the repo. Create no scratch or debug files (tests write only under `tmp_path`).
- Never commit to main/master, never push to main, never deploy, never merge. Work on branch `directive/goexplore-slice5-ab-report`; commit as you go and push the branch.
- No ROM, no `runs/` access.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Status meaning: set `Review` when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `src/pokeagent/goexplore/report.py` has `arm`, `archive_facts`, `compare`, `render`, `EQUAL_STEPS_TOLERANCE`, < 120 lines; `tools/go_explore_report.py` < 80 lines.
- [ ] Steps-to-milestone adds the presses of earlier returns, in name order. <!-- test: tests/test_goexplore_report.py::test_steps_to_milestone_adds_earlier_returns -->
- [ ] The comparable cell count is the union census over each arm's dirs; the archive count is a separate Go-Explore-only block. <!-- test: tests/test_goexplore_report.py::test_arm_counts_presses_shake_blackouts_and_cells -->
- [ ] A parent cycle in an archive terminates; a corrupt archive stops the report with exit 2. <!-- test: tests/test_goexplore_report.py::test_archive_facts_chain_and_non_organic -->
- [ ] No pass/fail verdict is printed.  <!-- test: tests/test_goexplore_report.py::test_render_has_the_no_verdict_line_and_dashes_for_none -->
- [ ] No file outside section 2 changed.
- [ ] Baseline gate, new tests and the full suite: 0 failed.

## 8. Report

Findings first: `wc -l` of the two files, any name or key that differed from the signatures above (the merged files win; report the difference), and anything about `extract_metrics` or `census` that conflicted with section 1. Then the real output tails: baseline gate, new tests, the full-suite line. State plainly that no ROM and no subprocess was used and that the real A/B, discoveries per 1k, floor progress and the dated note are the controller's.

## Required from User

Nothing for the build. Queue only after slice 4 has merged. The A/B itself needs the laptop and an organic `heal_cerulean` checkpoint (the controller's step).

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/go-explore-2026-11-14.md)
- Read(src/pokeagent/evaluation_ab.py)
- Read(src/pokeagent/goexplore/census.py)
- Read(src/pokeagent/goexplore/store.py)
- Read(src/pokeagent/goexplore/archive.py)
- Read(tests/test_goexplore_census.py)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(wc)
