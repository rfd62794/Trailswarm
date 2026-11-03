# PokeAgent: one-window viewer with human steering - game frame, agent console, keyboard, pause

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`. Depends on only what is on `main`
(`Agent_Loop_And_CLI_Directive.md` merged: `agent.py`, `prompt.py`, `runlog.py`, `console.py`, `cli.py`). If any of
`cli.py`, `agent.py`, `prompt.py`, `runlog.py`, `console.py` or `emulator.py` is missing from your worktree, stop
and write that in the Status row. **Do not list the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree`
are refused by the sandbox and end the run); use `git ls-files`.

## 1. Why this exists

Robert watches the run in PyBoy's own SDL2 window and reads the agent's thinking in a separate terminal. He wants
one window: game on the left, the agent console on the right, and the ability to take the controls for a moment
(nudge the player out of a corner, dismiss a box) without stopping the run. Verified facts (2026-11-02):

- PyBoy 2.9's SDL2 window owns its keys (arrows, `a` = A, `s` = B, Enter = Start, Backspace = Select). PyBoy owns
  that window, so a tkinter viewer must bind keys itself. Robert's correction: in the viewer, either Shift key is
  SELECT (not Backspace). tkinter and Pillow (with `ImageTk`) are available; no new dependencies are allowed.
- `Emulator.screenshot() -> Image.Image` returns the 160x144 RGB frame (and now renders one frame itself), so the
  viewer can run PyBoy headless (`window="null"`) and draw frames into tk.
- A run already logs every step to `runs/<ts>/log.jsonl` through `RunLog.append(entry: dict)`; the prompt already
  shows recent entries to the model. Human presses must appear in both so the agent knows the world was moved.

## 2. Scope

Create, in order:

1. `src/pokeagent/steering.py` - `SteeringController`: all logic, no tkinter import (testable without a Tk root).
2. `src/pokeagent/viewer.py` - `Viewer`: the tkinter widgets, frame drawing, key binding, the emulator proxy.
3. Small edits: `prompt.py` (human-line rendering), `console.py` (`print_human`), `runlog.py` (a lock in `append`),
   `agent.py` (optional `before_step` hook and `"source": "agent"` on its log entries), `cli.py` (`--sdl`).
4. `tests/test_steering.py`, and additions to the existing prompt/console/agent tests.

## 3. The work

### Architecture (decided; do not revisit)

The emulator is single-threaded and lives on the **tk thread**. The agent loop runs in a **worker thread** and
reaches the emulator only through `ViewerEmulator`, a proxy implementing the `Emulator` protocol
(`press`, `tick`, `read`, `read_range`, `screenshot`, `save_state`, `load_state`, `close`). Each proxy method puts
`(fn, Future)` on a `queue.Queue` and blocks on the future; the tk thread drains that queue inside a
`root.after(16, self._pump)` callback, executing each `fn(real_emu)` and resolving its future (exceptions travel
back through the future). When the queue is empty the pump calls `real_emu.tick(1)` and redraws the frame via
`ImageTk.PhotoImage(real_emu.screenshot().resize((480, 432), Image.NEAREST))`, so the game idles at about 60 fps.
Commands run at full speed (headless emulation), then the frame is redrawn. Closing the window sets a stop flag;
the pump fails pending futures so the worker unblocks, and `Agent.run()` ends via its normal `finally`.

### `steering.py`

```python
KEY_TO_BUTTON = {"Up": Button.UP, "Down": Button.DOWN, "Left": Button.LEFT, "Right": Button.RIGHT,
                 "a": Button.A, "s": Button.B, "Return": Button.START,
                 "Shift_L": Button.SELECT, "Shift_R": Button.SELECT}

class SteeringController:
    def __init__(self, emu: Emulator, log: RunLog, out=sys.stdout): ...
    paused: bool                                  # toggled by key "p"; starts False
    def button_for_key(self, keysym: str) -> Button | None        # KEY_TO_BUTTON.get; "p" is not a button
    def handle_key(self, keysym: str) -> str | None               # returns "pause", "resume", "human:RIGHT" or None
    def press_human(self, button: Button) -> None                 # emu.press(button); log; console line
    def wait_if_paused(self, poll_s: float = 0.05) -> None        # worker side: sleeps while paused
    def human_record(self, button: Button) -> dict
```

`human_record` shape (exact keys): `{"step": <int>, "source": "human", "button": "RIGHT", "state": <GameState.as_dict()
read after the press>, "thinking": "", "note": "", "error": "", "backend_ms": 0}`. `step` is the number of the most
recent agent step (0 before the first). Agent entries gain `"source": "agent"`. `press_human` runs on the tk thread
and calls the real emulator directly; append through `RunLog.append`, which gets a `threading.Lock`.

### Prompt, console, agent

- `prompt.build_prompt(state, recent, notes, step, max_steps)` keeps its signature. For a recent entry whose
  `source == "human"` the line is `step N: HUMAN pressed RIGHT` (no thinking text); agent lines are unchanged.
- `console.print_human(button: str, out=sys.stdout)` prints exactly `human:    RIGHT` (4 spaces after the colon,
  matching `button:   `).
- `Agent.__init__` gains the keyword `before_step: Callable[[], None] | None = None`, called at the top of each
  step; the viewer passes `controller.wait_if_paused`. No other `Agent` change.

### `viewer.py`

Layout: left `Label` holding the 480x432 frame; right a read-only `Text` (about 60 columns) with tags `header`
(`--- step` lines), `thinking`, `button`, `error`, `human`. `ConsoleWriter` has `write(s)`/`flush()` and is passed as
`out` to `Agent` and the controller; it picks the tag from the line prefix and inserts via `root.after(0, ...)`
so worker-thread prints are tk-safe. `<Key>` events go to `controller.handle_key(event.keysym)`. A status label
shows `RUNNING` or `PAUSED (press p)`. `run_viewer(emu_factory, backend, log, max_steps, ...) -> RunResult` builds
everything, starts the worker thread, runs `root.mainloop()`, joins, returns the result.

### `cli.py`

`pokeagent run` (not `--headless`) opens the viewer, replacing the SDL2 window mode: PyBoy is created headless and
the viewer draws it. New flag `--sdl` keeps the old PyBoy SDL2 window as a fallback. `--headless` is unchanged
(no window, no tkinter import). Keep the injectable `_build_emulator` helper working for tests.

## 4. What NOT to do

- Do not create a `Tk()` root, `Toplevel` or any window in tests; `steering.py` must not import tkinter.
- Do not touch `emulator.py` (no new methods), `ram.py`, `backend.py`, `decision.py`.
- Do not call the emulator from the worker thread directly, and do not add a second emulator thread.
- Do not add dependencies, change `pyproject.toml` or `uv.lock`, or read outside the worktree.
- Do not add stuck detection, pathing, vision, or mouse controls. Do not bind Backspace to anything.

## 5. Verification

- `uv run pytest -q` green. New tests at least (all with `FakeEmulator`, no Tk root):
  `button_for_key` for the nine keysyms (both `Shift_L` and `Shift_R` -> SELECT) plus `p` -> None, `BackSpace` ->
  None and an unknown key -> None; `handle_key("Right")` presses `Button.RIGHT` on the fake and returns
  `"human:RIGHT"`; the `human_record` exact key set and `"source": "human"`;
  the log line written by `press_human` is valid JSON; `handle_key("p")` twice toggles `paused` True then False;
  `wait_if_paused` returns immediately when not paused and blocks (test with a thread and an event) when paused;
  `build_prompt` renders `step 4: HUMAN pressed RIGHT` for a human entry and the old line for an agent entry;
  `print_human("RIGHT", out)` writes exactly `human:    RIGHT\n`; `Agent` entries carry `"source": "agent"` and
  `before_step` is called once per step; `RunLog.append` from two threads yields only valid JSON lines.
- `uv run pokeagent run --help` lists `--sdl` and `--headless`; `uv run pokeagent run --backend claude` still
  refuses with exit 2.
- Controller check (not yours): open the viewer on the real ROM, press arrows, see `human:    RIGHT` and the
  position change; press `p`, see the agent stop; press `p` again.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-viewer-and-human-steering-directive`. Never commit to `main`, never push
  to it, never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 250 lines.

## 7. Completion criteria

- [ ] `steering.py` (`SteeringController`, `KEY_TO_BUTTON`) with no tkinter import
- [ ] `viewer.py` (`Viewer`, `ViewerEmulator`, `ConsoleWriter`, `run_viewer`) under 250 lines
- [ ] `prompt.py`, `console.py`, `runlog.py`, `agent.py`, `cli.py` edits as in section 3
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, the exact `human_record` JSON from a test, and any place `Agent`, `RunLog` or `cli.py`
differed from section 3 (say exactly what you used).

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Draft |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-02 · robert-claude-laptop · none → Draft — one-window viewer + human steering; Robert asked 2026-11-02; needs Agent_Loop_And_CLI merged
<!-- queue:end -->
