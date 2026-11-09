# Trailswarm: decision records keep the reason text, a vetoed step keeps what was wanted and why it was refused, and `pokeagent brain why` prints them

**Size:** M. **Assignee:** devin.

## 1. Why this exists

On 2026-11-08 diagnosing a stall meant reconstructing the reason from code. `decisions.jsonl` records what happened but not why: the reason text exists as `Decision.why` and is thrown away before the record is written. It already reaches the console log through `self.presser.press(decision.button, "agent", decision.why)`, but the console log is not a per-step, joinable record.

Real shapes, pasted because you cannot read outside this worktree.

A current `decisions.jsonl` line (about 215 bytes):

```json
{"step": 1, "behaviour": "procedures", "rule": "procedure_step", "button": "START", "map": 38, "x": 4, "y": 6, "goal_stage": "potion", "box": false, "battle": false, "outcome": "box", "reversal": false}
```

The matching `transitions.jsonl` line (same `step`; `source` is `"agent"`, `"human"` or `"claude"`; a human or claude press has NO engine decision row, claude presses via `ClaudeDriver` write a row with `"driver": "claude"` and `"why"` already set):

```json
{"step": 1, "from": [38, 4, 6], "button": "START", "to": [38, 4, 6], "moved": false, "textbox": "none", "text": ">POKéMON | ITEM | BCN | SAVE | OPTION | EXIT", "facing": "DOWN", "source": "agent"}
```

`src/pokeagent/explorer/decisions.py` today (the parts that change):

```python
FIELDS = ("step", "behaviour", "rule", "button", "map", "x", "y", "goal_stage", "box", "battle", "outcome", "reversal")

def make_record(step: int, behaviour: str, rule: str, button: str, before: tuple, stage: str,
                box: bool, battle: bool, outcome: str, reversal: bool = False) -> dict:
    return {"step": step, "behaviour": behaviour, "rule": rule, "button": button, "map": before[0], "x": before[1],
            "y": before[2], "goal_stage": stage, "box": box, "battle": battle, "outcome": outcome,
            "reversal": reversal}
```

`Decision` (`src/pokeagent/explorer/behaviours/base.py`):

```python
@dataclass
class Decision:
    button: str
    rule: str
    why: str = ""
    behaviour: str = ""
    after: Callable | None = None
    driver: str = ""
```

`Engine.step` in `src/pokeagent/explorer/engine.py` today (the veto section; line numbers 52-65 at base):

```python
decision = self.selector.choose(ctx)
...
decision = loop_veto.check(ctx, self.selector, decision)  # a dead (situation, button) is skipped, not re-pressed
self.last_decision = decision
why_veto = veto(ctx, decision)
if why_veto:  # the policy table says this talk teaches nothing: B instead of A (keeps the loop guards counting)
    retalk_memory.note(ctx, decision)  # and the planner must not choose this talk again
    decision = Decision("B", "retalk_veto", why_veto, behaviour=decision.behaviour)
why_toss = toss_veto(ctx.view.lines, decision)
if why_toss:  # a toss screen is up: nothing may advance it, whichever behaviour pressed
    decision = Decision("B", "toss_veto", why_toss, behaviour=decision.behaviour)
...
rec = make_record(ctx.step, decision.behaviour, decision.rule, decision.button, before,
                  stage, box, battle, outcome, reversal)
if ctx.bandit is not None:
    rec = ctx.bandit.tag(rec)  # driver/arm: only runs with the bandit on carry them
if decision.driver:
    rec = {**rec, "driver": decision.driver}  # par_follow drove this press
```

Three places can replace the chosen `Decision`: `loop_veto.check` (returns the original object, or a re-chosen one from another behaviour), `retalk_veto` (new `Decision("B", "retalk_veto", ...)`) and `toss_veto` (new `Decision("B", "toss_veto", ...)`). In all three the original plan, including its `why`, is currently lost. In the vetoed cases the replacement's own `why` IS the refusal reason (`why_veto` / `why_toss`, or the re-chosen behaviour's own reason).

## 2. Scope

In order:

1. `src/pokeagent/explorer/decisions.py`: add `why` to the record, a length cap, and a helper for the planned-and-refused fields.
2. `src/pokeagent/explorer/engine.py`: pass the reason, remember the original plan, attach it when the step was substituted.
3. `src/pokeagent/brain/why.py` — pure logic: join and select steps. <!-- new: src/pokeagent/brain/why.py -->
4. `src/pokeagent/cli_brain_why.py` — the `why` subcommand, attached from `cli_brain.py` by one call. <!-- new: src/pokeagent/cli_brain_why.py -->
5. `src/pokeagent/cli_brain.py`: exactly two added lines at the end of `_add_commands` (see 3.4).
6. `tests/test_decision_why.py` — new tests. <!-- new: tests/test_decision_why.py -->

## 3. The work

### 3.1 The reason in every decision record

In `decisions.py`:

- Add the constant `WHY_CAP = 120`.
- Add `bound_why(text: str, cap: int = WHY_CAP) -> str`: collapse all runs of whitespace (including newlines) to one space, strip, and if longer than `cap` return the first `cap - 3` characters followed by `...` (ASCII, so the result is at most `cap` characters). `None` or non-str input returns `""`.
- `make_record` gains a last parameter `why: str = ""` and puts `"why": bound_why(why)` in the dict, after `"reversal"`.
- `FIELDS` gains `"why"` at the end. `FIELDS` is the list of keys every ordinary press record carries.
- Engine: `make_record(..., outcome, reversal, why=decision.why)`.

Size impact, from the record shape: a record is about 215 bytes today. `, "why": ""` plus the text adds 11 bytes plus at most 120 characters, so at most about 130 bytes per record (about +60% worst case); the longest literal `Decision(...)` reason strings in the behaviours are about 100 characters, so typical growth is 50-110 bytes per record (about +25-50%). A 400-step run goes from about 85 KB to at most about 135 KB. That is accepted; the cap is what keeps an f-string that embeds a long list from blowing it up.

Old records without `why` must stay readable: no reader may require the key. Everything new uses `rec.get("why")`.

`src/pokeagent/intervene/rig.py` already sets `rec["why"] = why` after `make_record` for claude presses (unbounded, short by nature). Leave `rig.py` as it is: its `why` simply overwrites the default `""`.

### 3.2 A vetoed step keeps what was wanted and why it was refused

Decision: the record's `why` is the reason of the decision that was actually pressed (for a veto, the refusal reason), and the original plan rides along in three extra keys that exist ONLY on substituted steps, like the existing optional `driver` key:

```json
{"step": 17, "behaviour": "plan_goal", "rule": "retalk_veto", "button": "B", ..., "why": "info NPC already memorised: B instead",
 "planned_button": "A", "planned_rule": "talk_adjacent", "planned_why": "Talk to the guard to learn the way out"}
```

- In `decisions.py` add `PLANNED_FIELDS = ("planned_button", "planned_rule", "planned_why")` and `with_plan(rec: dict, planned) -> dict`, which returns `{**rec, "planned_button": planned.button, "planned_rule": planned.rule, "planned_why": bound_why(planned.why)}`. It takes the `Decision` duck-typed; do not import `Decision` into `decisions.py`.
- `behaviour` in the vetoed record stays as it is today: the behaviour that planned the press (the retalk and toss vetoes already pass `behaviour=decision.behaviour`), so `rule` says who refused and `behaviour` says who wanted it.
- In `Engine.step`, right after `decision = self.selector.choose(ctx)` returns a non-empty button decision (that is, after the early `return` for a wait), keep `planned = decision`. After the toss veto and before `make_record`, if `decision is not planned`, apply `rec = with_plan(rec, planned)` right after `make_record`. This covers all three substitution points with one comparison and changes no veto logic. For `loop_veto.check`, which returns the original object when it does not veto, identity is the right test.
- Do NOT edit `retalk_veto.py`, `loop_veto.py` or `toss_guard.py`.

### 3.3 `src/pokeagent/brain/why.py` (pure, no argparse, no printing)

```python
def steps_of(run_dir: Path, step: int, around: int = 0) -> list[dict]
```

- Window is `step - around` to `step + around` inclusive (clamp the low end at 1). `around` below 0 is treated as 0.
- Read `decisions.jsonl` and `transitions.jsonl` with the tolerant reader `pokeagent.review.load.jsonl(path)` (missing file gives `[]`; corrupt lines are dropped). Import it from there; do not write a second reader.
- Decision rows: ignore rows with an `"event"` key; if several rows share a step keep the first.
- Join by `step`. Return one dict per step that appears in EITHER file inside the window, ascending by step, with these keys (use `None` where unknown):
  `step`, `map`, `x`, `y`, `behaviour`, `rule`, `button`, `why`, `outcome`, `source`, plus `planned_button`, `planned_rule`, `planned_why` only when the decision row has them.
- `source` comes from the transition row (`"agent"`, `"human"`, `"claude"`). `map/x/y` come from the decision row, else from the transition's `from` list. `button` comes from the decision row, else the transition. A step present only in `transitions.jsonl` (a human or claude press, no decision row) has `behaviour/rule/why/outcome` as `None`.
- If `decisions.jsonl` is absent AND `transitions.jsonl` is absent, raise `FileNotFoundError` with the run dir in the message. If either exists, return what there is. A step in the window with no rows anywhere is simply not returned.
- Add `render_text(rows: list[dict]) -> str`: one block per step. First line `step 17  map 38 (4,6)  agent  A -> B  outcome blocked`; second line `  behaviour plan_goal  rule retalk_veto`; third line `  why: <reason>`. When the row has `planned_*`, add `  wanted: A via talk_adjacent -- <planned_why>`. When `why` is `None` and the step has a decision row, print `  why: (not recorded: run predates reason logging)`; when there is no decision row at all print `  (no decision row: <source> press)`. Mark a non-agent source visibly by uppercasing it (`HUMAN`, `CLAUDE`).

### 3.4 `pokeagent brain why`

New module `src/pokeagent/cli_brain_why.py`, under 120 lines:

```python
def attach(bsub) -> None:   # bsub is the subparsers object passed to _add_commands
```

It adds the subcommand `why` with positional `run_dir` (`RUN_DIR`), positional `step` (int), `--around N` (int, default 0) and `--text` (store_true, human-readable; default is stable JSON, `indent=1, sort_keys=True`, matching the other brain commands). JSON shape: `{"run": "<run dir name>", "steps": [ ...rows from steps_of... ]}`. An error (missing run dir, no decisions and no transitions, `step < 1`) prints `{"error": "..."}` as JSON (or `error: ...` with `--text`) and the function returns exit code 1. Define the tiny emit and error helpers inside this module; do not import them from `cli_brain.py` (that would be a circular import), and do not depend on the `docs/memory-tools-on-brain` branch (PR #182) in any way: it adds `cli_brain_memory.py` and `cli_brain_runs.py` and a `brain assists` command that reads the same two files, and may or may not be merged first.

In `src/pokeagent/cli_brain.py` (277 lines, limit 300) add exactly these two lines as the LAST lines of `_add_commands`, after the `q.set_defaults(func=_cmd_q)` line, and change nothing else in the file:

```python
    from pokeagent.cli_brain_why import attach as _attach_why
    _attach_why(bsub)
```

The standalone `main()` in `cli_brain.py` builds the same commands without the `brain` prefix, so tests call `main(["why", str(run_dir), "17", "--around", "2"])`. Do NOT edit `src/pokeagent/cli.py`; it reaches the new command through `cli_brain.register` already.

### 3.5 Tests, `tests/test_decision_why.py`

Synthetic only: build run dirs under `tmp_path` with hand-written jsonl. Cover:

- `bound_why`: short text unchanged; 300 characters returns exactly 120 ending in `...`; newlines and runs of spaces collapse; `None` returns `""`.
- `make_record(...)` carries `why`, and `why=` over the cap is bounded; the default `""` works.
- `with_plan`: adds exactly the three `PLANNED_FIELDS` keys and bounds `planned_why`.
- Engine: reuse the fixture helpers the existing engine test uses (`make_ctx` in `tests/test_explorer_behaviours.py`, see `test_engine_presses_and_writes_complete_decision_lines`; copy the few lines you need into the new test file rather than importing a test module) to run a few steps with a stub selector. One case: an ordinary press has `rec["why"] == decision.why` and no `planned_*` keys. One case: force a `toss_veto` substitution (monkeypatch `pokeagent.explorer.engine.toss_veto` to return `"toss screen up"` and the selector to return `Decision("A", "talk", "wants to talk")`) and assert the record has `rule == "toss_veto"`, `why == "toss screen up"`, `planned_button == "A"`, `planned_rule == "talk"`, `planned_why == "wants to talk"`.
- Old records: `steps_of` over a run whose decisions have no `why` key returns `why is None` and does not raise, and `render_text` prints the `(not recorded: run predates reason logging)` line.
- `steps_of` join: agent step with both rows; a human step present only in `transitions.jsonl` (`source == "human"`, `rule is None`); `--around 1` returns three steps; an `"event"` row in decisions is ignored; step window clamped at 1; missing `decisions.jsonl` but present `transitions.jsonl` still returns rows; both missing raises `FileNotFoundError`.
- CLI: `main(["why", str(run), "2", "--around", "1"])` prints valid JSON with a `steps` list (use `capsys`), `--text` prints the `step 2` header and `why:` line, and a missing run dir returns 1 with an `error` key.

## 4. Which existing assertions may change

Check done at base: `FIELDS` is read in exactly one test file, `tests/test_explorer_behaviours.py`, at line 16 (import) and in `test_engine_presses_and_writes_complete_decision_lines` at lines 227 and 230:

```python
        assert set(rec) == set(FIELDS)                                              # line 227
    assert make_record(1, "b", "r", "A", (1, 2, 3), "potion", False, False, "none").keys() == set(FIELDS)   # line 230
```

Because `why` is added to BOTH `make_record` and `FIELDS`, neither assertion needs to change, and none should. Only if line 227 fails because one of those four steps was vetoed (it should not be; check) may you change that one line to `assert set(rec) - set(PLANNED_FIELDS) == set(FIELDS)` and add `PLANNED_FIELDS` to the line 16 import. No other test may be edited. Other tests read decision rows only by key (`tests/test_exploration_momentum.py` reads `reversal`, `tests/test_bandit.py` reads `driver`/`arm`, `tests/test_intervene_lease.py` reads `driver`/`rule`/`button`), and `tests/test_stalls.py:31` hand-builds a row without `why`, which must keep working.

## 5. What NOT to do

- Do not touch `src/pokeagent/game`, `src/pokeagent/cli.py` (another phase is changing those), `retalk_veto.py`, `loop_veto.py` or `toss_guard.py`, and do not change any veto's behaviour or decision.
- Do not change `src/pokeagent/intervene/rig.py` or `ClaudeDriver`.
- Do not change what is written to `transitions.jsonl` or the arguments to `self.presser.press(...)`. This is what keeps the golden trace hash stable (see 6).
- Do not add the `brain assists`, `cli_brain_memory.py` or `cli_brain_runs.py` pieces from PR #182; do not branch from or depend on that branch.
- Do not run the ROM-gated golden test as a pass signal; do not read, create, copy or print any ROM, `kb/`, `baselines/` or `runs/` data (gitignored, so missing in a fresh worktree; that is correct).
- Do not say where any game copy came from, in code, comments, docs or the report.
- No file over 600 lines; `cli_brain.py` must stay under 300 lines. The new modules are single-purpose.

## 6. The golden hash

`tests/test_golden_red.py` pins the sha256 of `transitions.jsonl` (run name masked), not `decisions.jsonl`. `write_transition` builds its line from the press frame only (`step`, `from`, `button`, `to`, `moved`, `textbox`, `text`, `facing`, `source`, extras); the decision record is never read there. `decision.why` already reached the presser before this change, and this change adds no extra call that consumes the emulator, the RNG or `ctx` state: the record is built after the press. By reading the code the hash cannot change. State that in the report, and state it as an expectation: that test needs the ROM, `kb/rom_tables.json` and `baselines/bedroom.state`, none of which exist in your worktree, so it will skip. Report it as NOT RUN. Claude runs it with the ROM present before merge. (kb/rom_tables.json is gitignored, so missing in a fresh worktree.)

## 7. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_decision_why.py
```
Expected: all pass, none skipped.

```
uv run pytest -q -p no:cacheprovider tests/test_explorer_behaviours.py tests/test_exploration_momentum.py tests/test_bandit.py tests/test_intervene_lease.py tests/test_toss_guard.py tests/test_stalls.py tests/test_par_follow.py tests/test_brain_query.py
```
Expected: same result as on your base commit with no new failures; report any pre-existing failure separately.

```
uv run pytest -q -p no:cacheprovider tests/test_golden_red.py -rs
```
Expected: SKIPPED for missing local files. Report it as NOT RUN, not as passed.

```
uv run python tools/brain.py why --help
```
Expected: usage text listing `run_dir`, `step`, `--around` and `--text`.

```
git diff --stat main -- src/pokeagent/game src/pokeagent/cli.py src/pokeagent/explorer/retalk_veto.py src/pokeagent/explorer/loop_veto.py src/pokeagent/intervene
```
Expected: no output.

## 8. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 9. Completion criteria

- [ ] Every ordinary decision record has a `why` of at most 120 characters; old records without it are still read everywhere. <!-- test: tests/test_decision_why.py -->
- [ ] A step substituted by `loop_veto`, `retalk_veto` or `toss_veto` carries `planned_button`, `planned_rule`, `planned_why`; an unsubstituted step carries none. <!-- test: tests/test_decision_why.py -->
- [ ] `pokeagent brain why RUN_DIR STEP [--around N] [--text]` prints position, behaviour, rule, reason, outcome and source per step, joining by step, and a human press with no decision row is shown as such. <!-- test: tests/test_decision_why.py -->
- [ ] `cli_brain.py` changed by exactly the two lines in 3.4 and is under 300 lines; no veto module changed.
- [ ] The two existing `FIELDS` assertions pass unchanged (or the single stated line changed, with the reason).
- [ ] `tests/test_golden_red.py` reported NOT RUN (skips without the ROM); no ROM, kb, baseline or runs data added.

## 10. Report

Findings first: confirm the record shape and cap, the exact veto design as built, which assertions (if any) changed and why, and that `tests/test_golden_red.py` was NOT RUN with the reasoning from section 6. Then the command tails from section 7.

## Required from User

Before merge, Claude runs `uv run pytest -q -p no:cacheprovider tests/test_golden_red.py -rs` on the laptop with the ROM present and confirms the pinned `EXPECTED_SHA256` is unchanged. That check is not part of this directive.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(src/pokeagent/explorer/decisions.py)
- Read(src/pokeagent/explorer/engine.py)
- Read(src/pokeagent/cli_brain.py)
- Read(tests/test_explorer_behaviours.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(uv run python tools/brain.py)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 19:26 · robert-claude-laptop · none → Queued — Approved by Robert 2026-11-08: record each decision's reason and add brain why
<!-- queue:end -->
