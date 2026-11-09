# Trailswarm: a repeatable hands-off regression that proves the agent reaches a milestone alone, with zero human or claude presses

**Size:** M. **Assignee:** devin.

## 1. Why this exists

On 2026-11-08 a claim that a fix worked was wrong. The owner had been helping the run by hand, and nobody checked `transitions.jsonl`, whose `source` field says who pressed. A cold agent (bedroom state, no map memory) finishes the potion goal by step 35 unaided; that is the measured baseline this regression protects.

Real shapes, pasted because you cannot read outside this worktree.

`transitions.jsonl`, one line per press (written by `write_transition` in `src/pokeagent/explorer/press.py`; `source` is `"agent"`, `"human"` or `"claude"`):

```json
{"step": 1, "from": [38, 4, 6], "button": "START", "to": [38, 4, 6], "moved": false, "textbox": "none", "text": ">POKéMON | ITEM | BCN | SAVE | OPTION | EXIT", "facing": "DOWN", "source": "agent"}
{"step": 2, "from": [38, 4, 6], "button": "DOWN", "to": [38, 4, 6], "moved": false, "textbox": "dialog", "text": "POKéMON | >ITEM | BCN | SAVE | OPTION | EXIT", "facing": "DOWN", "source": "agent"}
```

`decisions.jsonl` (agent presses only; claude presses carry `"driver": "claude"`; bandit/anomaly extras are lines with an `"event"` key and must be ignored):

```json
{"step": 1, "behaviour": "procedures", "rule": "procedure_step", "button": "START", "map": 38, "x": 4, "y": 6, "goal_stage": "potion", "box": false, "battle": false, "outcome": "box", "reversal": false}
```

`goal_frames.jsonl`, one line per goal first reached IN THIS RUN, appended by `record_goals` in `src/pokeagent/explorer/press_goals.py` (and, for a stop-at-map segment, a line with `"goal": "map:0x28"` from `press_stop.py`):

```python
fh.write(json.dumps({"goal": g, "step": ctx.step, "frame": ctx.frame}) + chr(10))
# e.g. {"goal": "potion", "step": 35, "frame": 4210}
```

A goal already true at the start state is NOT written (it is `initial_goals`, recorded in `meta.json` as `"initial_goals": ["...", ...]`), so a missing goal line can mean "assumed done at start", not "never reached".

`goal_stage` in `src/pokeagent/explorer/decisions.py` is the first goal in `GOALS` (from `pokeagent.goals`) not yet reached, else `"done"`:

```python
def goal_stage(goals: dict) -> str:
    return next((g for g in GOALS if not goals.get(g)), "done")
```

How the existing golden test isolates a run (`tests/test_golden_red.py`): it copies `tools/` and `src/` into pytest's tmp dir, plus `roms/Pokemon Red.gb`, `baselines/bedroom.state` (+ optional `.meta.json`) and `kb/rom_tables.json`, makes an empty `runs/`, then runs the demo with `cwd` set to that tmp dir: (kb/rom_tables.json is gitignored, so missing in a fresh worktree.)

```python
subprocess.run([sys.executable, "tools/explore_demo.py", "--headless", "--state", "baselines/bedroom.state",
                "--stop-at-goal", "potion", "--steps", "400", "--seed", "42", "--maps", str(maps),
                "--control-port", str(port)], cwd=cwd, check=True, capture_output=True, timeout=600)
(run,) = set((cwd / "runs").glob("explore-*")) - before
```

Why the copy must include `src`: `tools/explore_demo.py` does `sys.path.insert(0, <its parent's parent>/src)`, so the scratch `src` wins; and `src/pokeagent/knowledge/kb.py` finds the kb with `Path(__file__).resolve().parents[3] / "kb" / "rom_tables.json"`, which is the scratch root only when `src` itself lives in the scratch tree. Skip either and the run silently reads or writes the live `kb/` and `runs/`. A run with no existing `--maps` file starts with empty map memory.

## 2. Scope

New files only, in this order:

1. `src/pokeagent/review/hands_off.py` — pure judge: read a run dir, return a verdict. <!-- new: src/pokeagent/review/hands_off.py -->
2. `src/pokeagent/review/hands_off_cases.py` — load and validate the case table, decide skips. <!-- new: src/pokeagent/review/hands_off_cases.py -->
3. `tools/hands_off_cases.json` — the checked-in case table. <!-- new: tools/hands_off_cases.json -->
4. `tools/hands_off_check.py` — thin CLI: build the scratch copy, run, judge, print. <!-- new: tools/hands_off_check.py -->
5. `tests/test_hands_off.py` — synthetic tests. <!-- new: tests/test_hands_off.py -->

## 3. The work

### 3.1 The case table, `tools/hands_off_cases.json`

```json
{"cases": [
  {"name": "red_bedroom_potion_cold", "game": "red", "state": "bedroom", "memory": "none",
   "goal": "potion", "budget": 105, "seed": 42}
]}
```

- `state` is a name: it means `baselines/<state>.state`.
- `memory` is `"none"` (no maps file: the run starts blind) or `"live"` (copy `runs/maps.json` into the scratch tree, read only; skipped when absent). (runs/maps.json is gitignored, so missing in a fresh worktree.)
- `budget` is a step budget: 105 is 3x the 35 steps seen. A pass needs the goal line with `step <= budget`.
- `game` selects the ROM: only `"red"` exists, mapping to `roms/Pokemon Red.gb`. Keep that mapping as one small dict in `hands_off_cases.py`.
- Add no other case. This one is the proven baseline; a case that has not been seen to pass would be a guess.

### 3.2 `hands_off_cases.py`

- `load_cases(path) -> list[Case]` where `Case` is a frozen dataclass of the fields above. Raise `ValueError` with the case name on a missing field, a non-positive `budget`, an unknown `memory` or an unknown `game`. Do not validate `goal` against `GOALS` here (the demo's `--stop-at-goal` does).
- `skip_reason(case, root) -> str | None`: `None` when runnable, else a one-line reason naming the first missing input, checked in this order: ROM, `baselines/<state>.state`, `kb/rom_tables.json`, and for `memory == "live"` also `runs/maps.json`. Format: `"missing roms/Pokemon Red.gb"`. These are gitignored, so missing in a fresh worktree; that is expected and is a skip, never a failure.

### 3.3 `hands_off.py`, the judge

```python
@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: list[str]        # empty when passed; one short sentence per failure
    goal_step: int | None     # step of the goal line, None if absent
    presses: int              # rows in transitions.jsonl
    non_agent: int            # rows whose source is not "agent"

def judge_run(run_dir: Path, goal: str, budget: int) -> Verdict
```

Read with the tolerant reader `pokeagent.review.load.jsonl(path, skipped)` (missing file gives `[]`, a corrupt line is counted in `skipped[path.name]`). Read `meta.json` with `pokeagent.review.load.load_json`. Pass only when ALL hold; collect every failing reason, do not stop at the first:

1. `transitions.jsonl` is missing or has no rows: fail, reason `"transitions.jsonl missing or empty"`.
2. Any `transitions.jsonl` line was skipped as corrupt: fail (zero human presses cannot be proven). Reason names the count.
3. Any row whose `source` is not exactly `"agent"` (including a missing key): fail. Reason names the count, the sources seen, and the first five step numbers, e.g. `"2 non-agent presses (human) at steps 12, 13"`.
4. `goal_frames.jsonl` has no row with `goal == goal`: fail, reason `"goal potion never reached"`; if the file itself is missing say `"goal_frames.jsonl missing"`. If `meta.json` lists the goal in `initial_goals`, say instead `"goal potion was already true at the start state (initial_goals)"`.
5. The goal row's `step` is greater than `budget`: fail, reason `"too slow: potion at step 140, budget 105"`. A row with a non-integer `step` fails with `"goal row has no integer step"`.

Never raise on a bad run dir; a nonexistent directory yields a failed verdict (reasons 1 and 4). Keep the module under 150 lines.

### 3.4 `tools/hands_off_check.py`, the thin tool

Usage:

```
uv run python tools/hands_off_check.py                     # every case in tools/hands_off_cases.json
uv run python tools/hands_off_check.py --case red_bedroom_potion_cold
uv run python tools/hands_off_check.py --keep               # keep the scratch dir and print its path
uv run python tools/hands_off_check.py --judge RUN_DIR --goal potion --budget 105   # judge an existing run, run nothing
```

Per case: compute `skip_reason(case, ROOT)`; if set, print `SKIP <name>: <reason>` and move on (exit 0 for skips). Otherwise:

1. Make a scratch dir with `tempfile.mkdtemp(prefix="hands-off-")`.
2. Copy `tools/` and `src/` (ignore `__pycache__`), the ROM, `baselines/<state>.state` (+ `.state.meta.json` if present) and the whole `kb/` dir into it, preserving relative paths, exactly as `tests/test_golden_red.py` does. Make an empty `runs/`. For `memory == "live"` copy `runs/maps.json` to scratch `runs/maps.json`.
3. Run `sys.executable tools/explore_demo.py --headless --state baselines/<state>.state --stop-at-goal <goal> --steps <budget> --seed <seed> --maps runs/maps.json --control-port <9100 + case index>` with `cwd` = scratch, `timeout=600`, `capture_output=True`. A non-zero exit or a timeout is reported as `ERROR <name>: <last 400 chars of stderr>` and counts as a failure.
4. Find the single new `runs/explore-*` dir and call `judge_run` on it.
5. Print `PASS <name>: <goal> at step N of budget B, 0 non-agent presses` or `FAIL <name>: <reasons joined by "; ">`, plus the scratch run dir path on a failure.
6. Remove the scratch dir with `shutil.rmtree(..., ignore_errors=True)` unless `--keep`.

Final line: `N passed, M failed, K skipped`. Exit 1 if any failed or errored, else 0. The tool never reads or writes the live `runs/` or `kb/` except the read-only copies listed above. Keep the tool under 150 lines; the verdict logic stays in `hands_off.py`.

### 3.5 Tests, `tests/test_hands_off.py`

Everything is synthetic. Build a fake run dir under `tmp_path` with hand-written `transitions.jsonl`, `decisions.jsonl`, `goal_frames.jsonl` and `meta.json`, using a small helper `make_run(tmp_path, sources, goal_step, ...)`. Never start an emulator and never run the tool's subprocess. Cover at least:

- pass: 35 agent rows, `goal_frames` has `potion` at 35, budget 105: `passed` is true, `reasons == []`, `goal_step == 35`.
- pass at the boundary: goal at step 105 passes; at step 106 fails with `"too slow"`.
- too slow: goal at 140 fails, the reason mentions 140 and 105.
- any human press fails even when the goal is in budget: one `"human"` row among agent rows; reason mentions `human` and the step.
- a `"claude"` row fails; a row with no `source` key fails.
- missing `transitions.jsonl` fails; empty file fails; missing `goal_frames.jsonl` fails with `"goal_frames.jsonl missing"`.
- goal in `meta.json` `initial_goals` and no goal line: the `initial_goals` reason.
- a corrupt (non-JSON) line in `transitions.jsonl` fails and is counted.
- a nonexistent run dir returns a failed verdict and does not raise.
- all reasons are collected together (human press AND too slow gives two reasons).
- cases: `load_cases` on the checked-in `tools/hands_off_cases.json` returns the one case with `budget == 105` and `goal == "potion"`; a bad `memory` value raises `ValueError` naming the case; `skip_reason` returns text starting with `missing roms/` against an empty `tmp_path`, and `None` when you create the four input files as empty placeholder files under `tmp_path`.

## 4. What NOT to do

- Do not touch `src/pokeagent/game`, `src/pokeagent/cli.py` (another phase is changing those), `tests/test_golden_red.py`, `src/pokeagent/explorer/retalk_veto.py` or `loop_veto.py`.
- Do not run the explorer or the emulator, and do not add a test that needs a ROM, `kb/` data, a baseline state or a `runs/` directory. Those files are gitignored, so missing in a fresh worktree; that is correct. Do not commit, create, copy, read or print any of them. The ROM-present run is Claude's, after merge.
- Do not add a pytest that shells out to `tools/hands_off_check.py` or calls its run function.
- Do not search, glob or hunt for the ROM or states. If an input is missing, the code skips with a reason; that is the whole behaviour.
- Do not say where any game copy came from, in code, comments, docs or the report.
- Do not add cases beyond the one in 3.1, and do not change `src/pokeagent/explorer/*`.
- No file over 600 lines; each new module has one job.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_hands_off.py
```
Expected: all pass, none skipped.

```
uv run python tools/hands_off_check.py
```
Expected in this worktree (no ROM): `SKIP red_bedroom_potion_cold: missing roms/Pokemon Red.gb`, then `0 passed, 0 failed, 1 skipped`, exit 0.

```
uv run pytest -q -p no:cacheprovider tests/test_cli_review.py tests/test_review_run.py tests/test_review_diff.py
```
Expected: same result as on your base commit; report any pre-existing failure separately.

```
git status --short
```
Expected: only the five new files from section 2.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] `judge_run` passes a clean 35-step agent run and fails on each of: any non-agent press, goal too slow, goal absent, missing or empty files, corrupt transitions line. <!-- test: tests/test_hands_off.py -->
- [ ] The case table loads, validates, and reports a stated skip reason when an input is missing. <!-- test: tests/test_hands_off.py -->
- [ ] `uv run python tools/hands_off_check.py` in this worktree prints a SKIP with a reason and exits 0.
- [ ] No new file is over 600 lines; no ROM, kb, baseline or runs data was added.
- [ ] Nothing outside the five files in section 2 changed.

## 8. Report

Findings first: any deviation from sections 3.1-3.5, the exact SKIP line the tool printed, and the pytest tails. State plainly that the ROM-present run (`uv run python tools/hands_off_check.py` on a machine with the ROM and states) was NOT run.

## Required from User

After merge, on the laptop with the ROM, `baselines/bedroom.state` and `kb/rom_tables.json` present, Claude runs `uv run python tools/hands_off_check.py` and confirms `PASS red_bedroom_potion_cold` (potion at about step 35, budget 105). That run is the real acceptance check and is not part of this directive.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/review/load.py)
- Read(tests/test_cli_review.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(uv run python tools/hands_off_check.py)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 19:26 · robert-claude-laptop · none → Queued — Approved by Robert 2026-11-08: repeatable hands-off milestone check that fails on any human press
<!-- queue:end -->
