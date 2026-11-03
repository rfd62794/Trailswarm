# PokeAgent design

Date: 2026-11-02. Owner: Robert (RFD IT Services). Builders: Devin via directives; Claude reviews.

## Intent and why

Robert wants an agent that plays Pokemon Red on its own, unattended, through PyBoy. The point is a
reusable framework: any agent (Claude through `claude -p` today, an SDK or free-model backend later)
can sit in a loop of "read the game, choose a button, press it, remember what happened". Robert
finds the failure modes (wandering, wall-bumping, dialog loops) the fun part, so the logs and notes
must make those visible.

## Goals

- A repo `PokeAgent` (uv, Python 3.12, `uv run`) that runs Pokemon Red via PyBoy 2.x.
- **Watchable (Robert, 2026-11-02):** a real run opens the PyBoy window (`window="SDL2"`, real-time speed)
  so Robert can watch the game, and the terminal shows the agent's thinking per step: state summary, the
  model's `thinking`, the button, the note. Headless (`window="null"`, speed 0) is for tests and `--headless`.
- A step loop: read state, build a prompt, ask a backend for one button, press it, log it.
- Run artifacts per run under `runs/<timestamp>/`: `log.jsonl` (every step), `notes.txt` (the agent's
  own memory, fed back each step), save-state snapshots.
- A pluggable backend: `claude -p` first, a stub for dry runs, room for an SDK backend (screenshots).
- Every module is testable with no ROM and no model, via a fake emulator and a scripted backend.
- Claude and Devin drive it the same way: `uv run pokeagent run --steps N --backend stub|claude`.

## Non-goals

- Beating the game, optimising play, or reinforcement learning.
- Vision in version one. State comes from RAM only; screenshots are a later backend.
- Sound or multi-ROM support. Red (UE) only. A visible window is in; a GUI beyond PyBoy's own is not.
- Any distribution of the ROM. The ROM is never committed (`roms/` is gitignored).

## Anti-goals (a failure even if it works)

- A run that burns subscription usage by surprise. The step cap defaults to 50 and a real backend
  needs an explicit `--steps`; no unbounded loop exists.
- Secrets or the ROM landing in git.
- One giant module. Small modules, one job each (Robert's SOLID/SRP/KISS rule).

## Constraints

- uv + Python 3.12, `uv run pytest -q` is the test command (verified: 3.12.12, pyboy 2.9.0).
- Devin runs non-interactively in a worktree. `roms/` is gitignored so **the ROM is not in Devin's
  worktree**; all directive tests must pass without it. ROM-dependent tests skip when `POKEAGENT_ROM`
  (path) is unset or missing.
- No install, download or fetch inside a directive run. `uv sync` already holds pyboy and pytest.
- ROM path comes from `--rom` or env `POKEAGENT_ROM`, default `roms/Pokemon Red.gb`.
- Verified ROM: SHA-1 `EA9BCAE617FDF159B045185467AE58B2E4A48B9A` (1,048,576 bytes).

## Design

Package `src/pokeagent/`, one job per module:

| Module | Job |
|---|---|
| `emulator.py` | `Emulator` protocol (`press(button, frames)`, `tick(n)`, `read(addr)`, `read_range`, `screenshot()`, `save_state(path)`, `load_state(path)`) plus `PyBoyEmulator` (headless `window="null"`, speed 0) and `FakeEmulator` (scripted memory, records presses) |
| `ram.py` | Address map and `read_state(emu) -> GameState` (frozen dataclass) |
| `backend.py` | `Backend` protocol (`choose(prompt) -> str`), `StubBackend` (scripted replies), `ClaudeCliBackend` (`claude -p` via subprocess, `shutil.which`, timeout) |
| `decision.py` | `parse_reply(text) -> Decision(button, note)`; tolerant of fenced JSON and stray prose; invalid reply becomes a safe `Decision("NONE", ...)` plus a recorded parse error |
| `prompt.py` | Builds the per-step prompt from state, last N log lines and notes |
| `runlog.py` | Run directory, `log.jsonl` writer, `notes.txt` read/append with a size cap |
| `agent.py` | The loop, wiring the above; stops on step cap, backend failure threshold, or Ctrl+C, always writing a final summary |
| `console.py` | Per-step console block (state, thinking, button, note, error) and the end-of-run summary |
| `cli.py` | `pokeagent run [--headless]`, `pokeagent check-rom` (hash and boot test), `pokeagent state` (print current RAM state) |

Buttons: `UP DOWN LEFT RIGHT A B START SELECT`, plus `NONE` (wait). A press holds 8 frames then
ticks 16 more so walking and text advance settle. Reply protocol the model must follow: one JSON
object, `{"thinking": "one or two sentences of reasoning", "button": "A", "note": "optional text to remember"}`.
`thinking` is shown on the console and logged; `note` is appended to `notes.txt`.

Console (module `console.py`): one block per step, plain `print`, e.g.

```
--- step 12/50  map=0x26 pos=(3,6) party=0 badges=0 battle=no money=3000
thinking: I'm in the bedroom facing the stairs; going down should lead outside.
button:   DOWN       note: stairs are at the top-right of the bedroom
```

plus `error:` when the reply failed to parse or the backend failed. Window mode: `--headless` flag;
default is visible. Visible runs use `set_emulation_speed(1)` so the game moves at human speed between
presses; headless uses 0.

### RAM map (from memory of pret/pokered `wram.asm`; UNVERIFIED)

Treated as claims to calibrate, not facts. The map lives in one table in `ram.py` so correcting an
address is a one-line change. Believed values: map id `0xD35E`, player Y `0xD361`, player X `0xD362`,
party count `0xD163`, badges `0xD356`, in-battle flag `0xD057`, money 3 bytes BCD at `0xD347`.
Calibration (a later step, by Claude or Robert, with the ROM): start a new game, confirm the map id
reads the bedroom (`0x26`) and coordinates change as the player walks, then fix the table.

### Stuck detection (phase 2, not version one)

Version one only logs position per step so wall-bumping is visible. Automatic nudges come after
Robert has seen real logs.

## Build order (directives, all in this repo)

1. `Emulator_Layer_Directive` - `emulator.py`, `FakeEmulator`, `ram.py`, `GameState`.
2. `Backend_And_Decision_Directive` - `backend.py`, `decision.py`.
3. `Agent_Loop_And_CLI_Directive` - `prompt.py`, `runlog.py`, `console.py`, `agent.py`, `cli.py` (needs 1 and 2).

Then, outside Devin: calibration run with the ROM, a 20-step stub run, a 50-step real run.

## Left to the builder

Internal class shapes, exact prompt wording, log field names beyond `step, state, button, note,
error`, test layout.

## Decisions I made (flag if wrong)

- Version one is RAM-only for the model's input, no screenshots (matches the pasted plan). Robert watches
  the screen himself through the PyBoy window.
- `claude -p` is called with the prompt on stdin and `--output-format text`; one fresh call per step,
  no session reuse, so the notes file is the only memory.
- Step cap default 50; a real backend with no `--steps` refuses to run.

## Builder-check answers (my calls, verified where noted)

- **`claude -p` isolation (verified 2026-11-02):** the exact command is
  `claude -p --tools "" --no-session-persistence --model <model> --output-format text`, prompt on
  stdin, run from the run directory. `--tools ""` disables every tool, so the agent cannot touch files
  or shell. Default model `haiku`, overridable with `--model`. A test call returned `{"button":"A"}`.
- **Failures:** backend timeout 120 s. A timeout, non-zero exit or unparseable reply becomes
  `Decision("NONE")` with `error` set in the log. Three consecutive failures stop the run
  (CLI exit code 2). Step cap reached is exit code 0.
- **Cold boot:** the agent plays from the title screen unless `--state PATH` loads a snapshot.
  Snapshots are written every 10 steps and at the end to `runs/<ts>/state_<step>.state`.
  `pokeagent save-state` is not built; a snapshot from any run is the baseline.
- **GameState (complete v1 field list):** `map_id:int, x:int, y:int, party_count:int, badges:int`
  (bitmask), `badge_count:int, in_battle:bool, money:int` (BCD decoded to a normal int).
  No dialog or menu flag in v1; dialog loops are visible in the log by repeated state and button.
- **Prompt:** last 10 log lines, notes file appended (never replaced), notes capped at 4000
  characters keeping the newest.
- **Dependencies between directives:** 1 and 2 touch separate files and run in parallel; 3 needs both
  and owns the `pokeagent` console entry point in `pyproject.toml`. The scaffold (pyproject, pyboy,
  pillow, pytest, `.gitignore`, smoke test) is committed before any directive runs.
- **`screenshot()`** returns a PIL `Image` (160x144 RGB); `FakeEmulator` returns a blank one.
  Pillow is already a dependency (PyBoy needs it for screen images).

## Demo integration rule (Robert, 2026-11-02)

`tools/explore_demo.py` is the living spike. It imports framework modules as they land (`screentext`, `names`,
`hexmap`, `textbox`, `mapmem`, `kb`, `viewer`) instead of keeping local copies. The framework reads the demo's data:
`runs/maps.json` and `runs/explore-*/transitions.jsonl`. Every directive carries a "Demo integration" item in its
Scope. The controller runs the demo after each merge, and Robert watches it.
