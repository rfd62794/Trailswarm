# PokeAgent: the loop - prompt, run log, console, agent, CLI

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`. This is build step 3 of 3. It depends on
`Emulator_Layer_Directive.md` and `Backend_And_Decision_Directive.md` being merged to `main` first: your branch
must already contain `src/pokeagent/emulator.py`, `ram.py`, `backend.py`, `decision.py`. If any of those four
files is missing from your worktree, stop and write that in the Status row; do not hunt or recreate them.

## 1. Why this exists

Robert wants to watch an agent play Pokemon Red in the PyBoy window while the terminal shows what it is
thinking each step. Directives 1 and 2 built the emulator seam and the model backend; this wires them into a
bounded loop with a per-run log, a notes file the agent reads back each step, a console view, and a CLI that
Claude, Devin and Robert all drive the same way.

Verified facts: test command `uv run pytest -q` (Python 3.12.12). `claude -p` is invoked by `ClaudeCliBackend`;
your run cannot call it, so every test uses `StubBackend` and `FakeEmulator`. The ROM is not in your worktree.

Interfaces you build on (from directives 1 and 2; read the files, do not change them):

- `emulator.Button`, `emulator.Emulator` (`press`, `tick`, `read`, `read_range`, `screenshot`, `save_state`,
  `load_state`, `close`), `emulator.PyBoyEmulator(rom_path, headless=...)`, `emulator.FakeEmulator`.
- `ram.read_state(emu) -> GameState` with `.as_dict()` and `.summary()`.
- `backend.Backend.choose(prompt) -> str`, `backend.BackendError`, `backend.StubBackend`,
  `backend.ClaudeCliBackend(model, timeout_s, cwd)`.
- `decision.parse_reply(text) -> Decision(button, thinking, note, error, raw)`.

## 2. Scope

Create, in order:

1. `src/pokeagent/prompt.py` - `build_prompt(state, recent: list[dict], notes: str, step: int, max_steps: int) -> str`.
2. `src/pokeagent/runlog.py` - `RunLog`: run directory, `log.jsonl`, `notes.txt`.
3. `src/pokeagent/console.py` - `print_step(...)`, `print_summary(...)`.
4. `src/pokeagent/agent.py` - `Agent.run() -> RunResult`.
5. `src/pokeagent/cli.py` - `pokeagent run | check-rom | state`, and the console entry point in `pyproject.toml`.
6. Tests for each, plus `README.md` (short: what it is, how to run, the cost warning).

## 3. The work

### `prompt.py`

The prompt states the goal ("You are playing Pokemon Red. Explore, talk to people, progress the story."),
the current `state.summary()`, the last 10 log entries as `step N: pressed X (thinking...)` lines, the notes
file verbatim under a `## Your notes` heading, and the reply contract: *Reply with exactly one JSON object:
`{"thinking": "...", "button": "UP|DOWN|LEFT|RIGHT|A|B|START|SELECT|NONE", "note": "optional, something worth
remembering"}`. No other text.* Pure function, no I/O.

### `runlog.py`

`RunLog(root: Path = Path("runs"), now=None)` creates `runs/<YYYYMMDD-HHMMSS>/`. `append(entry: dict)` writes
one JSON line to `log.jsonl` (fields at least `step, state, button, thinking, note, error, backend_ms`).
`recent(n=10) -> list[dict]` (kept in memory). `notes() -> str` reads `notes.txt` ("" if absent);
`add_note(text)` appends a line; after appending, if the file exceeds 4000 characters keep only the newest
4000 (cut at a line boundary). `state_path(step) -> Path` = `state_<step:04d>.state`. `write_summary(result)`
writes `summary.json`.

### `console.py`

`print_step(step, max_steps, state, decision, error_ms=None, out=sys.stdout)` prints exactly this shape:

```
--- step 12/50  map=0x26 pos=(3,6) party=0 badges=0 battle=no money=3000
thinking: I'm in the bedroom facing the stairs; going down should lead outside.
button:   DOWN       note: stairs are at the top-right of the bedroom
```

The `note:` part is omitted when empty; an `error:   <text>` line is added when `decision.error` is set.
`print_summary(result, out)` prints steps taken, stop reason, run directory, failure count. Plain `print`,
no third-party library, `out` injectable for tests.

### `agent.py`

```python
@dataclass
class RunResult: steps: int; stop_reason: str; run_dir: Path; failures: int

class Agent:
    def __init__(self, emu, backend, log: RunLog, *, max_steps: int, snapshot_every: int = 10,
                 max_consecutive_failures: int = 3, out=sys.stdout): ...
    def run(self) -> RunResult: ...
```

Per step: `state = read_state(emu)`; `prompt = build_prompt(...)`; `raw = backend.choose(prompt)` timed, with
`BackendError` caught -> `Decision("NONE", error=str(e))`; `decision = parse_reply(raw)`; `emu.press(Button[decision.button])`;
`log.append(...)`; `print_step(...)`; `if decision.note: log.add_note(decision.note)`; every `snapshot_every`
steps `emu.save_state(log.state_path(step))`. A step whose `decision.error` is set counts as a failure;
a clean step resets the counter; `max_consecutive_failures` in a row stops with `stop_reason="backend_failures"`.
Step cap -> `"max_steps"`. `KeyboardInterrupt` -> `"interrupted"`. Always: final snapshot, `write_summary`,
`print_summary`, `emu.close()` (in `finally`).

### `cli.py`

`argparse`, entry `main(argv=None) -> int`. Add to `pyproject.toml`: `[project.scripts] pokeagent = "pokeagent.cli:main"`
(this is the only `pyproject.toml` change allowed; do not touch dependencies or `uv.lock`).

- `pokeagent run [--rom PATH] [--backend stub|claude] [--model haiku] [--steps N] [--headless] [--state PATH]
  [--runs-dir runs]`. ROM default: `--rom`, else env `POKEAGENT_ROM`, else `roms/Pokemon Red.gb`. `--backend
  stub` defaults `--steps 20`; `--backend claude` with no `--steps` prints `refusing: --steps is required for a
  real backend (each step is one claude call)` and returns 2. `--state` loads a snapshot after boot. Exit codes:
  0 `max_steps`, 2 `backend_failures`, 130 `interrupted`.
- `pokeagent check-rom [--rom PATH]`: prints size and SHA-1, says `match` if SHA-1 is
  `EA9BCAE617FDF159B045185467AE58B2E4A48B9A` else `mismatch (expected ...)`, boots headless for 60 frames,
  prints `boot ok`; returns 0 on match and boot, 1 otherwise.
- `pokeagent state [--rom PATH] [--state PATH]`: boots headless, optionally loads the snapshot, ticks 60,
  prints `read_state(...).summary()`.

Factor the "build an emulator from args" step into one helper so tests can inject `FakeEmulator`.

## 4. What NOT to do

- Do not modify `emulator.py`, `ram.py`, `backend.py`, `decision.py`. If something you need is missing from
  them, work around it in your own module and say so in the report.
- Do not add stuck detection, pathing, vision, or a screenshot backend.
- Do not add dependencies (`rich`, `click`, etc.). `argparse` and `print` only.
- Do not call the real `claude` or open an SDL2 window in tests.
- Do not read outside the worktree, download, or install.

## 5. Verification

- `uv run pytest -q` -> green. New tests at least: prompt contains summary, notes, recent lines and the JSON
  contract; `RunLog` writes JSONL, `recent(10)` caps, notes append and 4000-char trim at a line boundary;
  `print_step` exact output with and without note and with error; `Agent` with `FakeEmulator` + `StubBackend`
  runs 5 steps and the fake recorded 5 presses; three unparseable replies in a row stop with
  `backend_failures`; a parse failure followed by a clean step resets the counter; snapshots written at
  `snapshot_every`; `cli.main(["run", "--backend", "claude"])` returns 2 without touching an emulator;
  `cli.main(["run", "--backend", "stub", "--steps", "3", "--headless"])` with the emulator factory patched to
  `FakeEmulator` returns 0 and leaves a `log.jsonl` with 3 lines in a tmp runs dir.
- `uv run pokeagent run --backend claude` -> the refusal line, exit 2 (no ROM needed, it refuses first).
- `uv run pokeagent --help` lists the three subcommands.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-agent-loop-and-cli-directive`. Never commit to `main`, never push
  to it, never merge.
- Create no scratch or debug files; test runs use `tmp_path`. If unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 250 lines.

## 7. Completion criteria

- [ ] `prompt.py`, `runlog.py`, `console.py`, `agent.py`, `cli.py` present and under 250 lines each
- [ ] `[project.scripts] pokeagent` entry point; `uv run pokeagent --help` works
- [ ] Tests listed in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] `README.md` with run instructions and the usage-cost warning
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, the exact console block from the 5-step fake run, and any decision not in the design.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Draft |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-02 21:54 · robert-claude-laptop · none → Draft — build step 3 of 3; queue only after Emulator_Layer and Backend_And_Decision are merged to main
<!-- queue:end -->
