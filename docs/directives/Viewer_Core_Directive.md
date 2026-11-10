# PokeAgent: viewer core - agent snapshot contract, control server, registry, viewer model (no UI yet)

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` sections 4.3 and 7a.
This is directive V1 of that design. V2 (the Dear PyGui window) builds on what this one delivers.
**Do not list the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree` are refused by the sandbox and
end the run); use `git ls-files`.

## 1. Why this exists

Robert has four viewers (`tools/explore_demo.py`, `tools/agent_window.py`, `tools/watch.py`,
`tools/webview.py`), each reading agents a different way: explore_demo serves an ad-hoc control API on port
8765 (`/status /goals /screen /screenshot.png /map /press /pause /resume /goto /say`), `tools/rl_train.py`
publishes its own status dict (`publish_status`), and `watch.py` scans ports 8765 and 8800-8815. He wants one
native window that shows every agent. That needs one contract every agent speaks and a viewer core that can
be tested without a display. Frames already travel through shared memory (`src/pokeagent/telemetry.py`:
`FramePublisher(agent_id, emu, half_res=False)`, `FrameSubscriber(agent_id).read() -> (bytes, w, h) | None`,
seqlock header: u64 seq at [0:8], u16 w [8:10], u16 h [10:12], RGB from byte 16; slot name
`pokeagent_frames_<id>`). Keep that; add the rest.

## 2. Scope (in order)

1. `src/pokeagent/snapshot.py` - the snapshot contract v1 (dataclasses, `to_dict`, `from_dict`).
2. `src/pokeagent/agent_registry.py` - discovery files under `runs/agents/`.
3. `src/pokeagent/control_server.py` - stdlib HTTP server thread: `GET /snapshot`, `POST /command`.
4. `src/pokeagent/viewer/` package, pure Python (no Dear PyGui import anywhere in this directive):
   `sources.py` (AgentSource protocol, `HttpShmSource`, `FakeSource`), `model.py` (latest snapshot + frame per
   agent, staleness), `layout.py` (grid maths + focus state), `commands.py` (command builders + key map).
5. `src/pokeagent/human_hold.py` (section 3.5).
6. Tests for all of the above.

## 3. The work

### 3.1 snapshot.py

```python
SCHEMA_VERSION = 1
DRIVERS = ("explorer", "rl", "human", "claude")

@dataclass
class Thinking:  want: str = ""; plan: str = ""; blocker: str = ""; driver: str = ""; rule: str = ""
                 button: str = ""; result: str = ""; confidence: float | None = None
@dataclass
class Goal:      id: str; name: str; status: str  # "done" | "current" | "ahead"
                 steps: int | None = None
@dataclass
class Segment:   id: str = ""; name: str = ""; steps: int = 0; record: int | None = None
@dataclass
class Sees:      rows: list[str] = field(default_factory=list); mode: str = "overworld"  # | "battle" | "menu"
@dataclass
class PartyMon:  species: str; level: int; hp: int; max_hp: int
@dataclass
class Screen:    box_text: str = ""; in_battle: bool = False; party: list[PartyMon] = ...; money: int | None = None
                 bag_summary: str = ""
@dataclass
class Event:     step: int; driver: str; text: str
@dataclass
class AgentSnapshot:
    agent_id: str; kind: str                       # "explorer" | "rl" | "hybrid" | other free text
    v: int = SCHEMA_VERSION
    state: str = "running"                         # running | paused | stopped | done
    stop_reason: str = ""; step: int = 0
    segment: Segment; goals: list[Goal]; thinking: Thinking
    drivers: dict[str, int]                        # presses per driver over the last 100 presses
    drivers_available: list[str]                   # which "Hand to" targets this agent supports
    recent: list[Event]                            # newest last, at most 20 (to_dict truncates)
    sees: Sees; screen: Screen
    frame_slot: str = ""; updated_at: float = 0.0  # time.time() when built
```
(Write it as proper multi-line dataclasses; the block above is the field list.) `from_dict` ignores unknown keys,
fills missing keys with defaults, never raises on a missing optional field, and raises `ValueError` only when
`agent_id` is missing or `v` is greater than `SCHEMA_VERSION`. Also `DriverWindow(maxlen=100)`: `.add(driver)`,
`.counts() -> dict` (all four drivers present, zeros included) - agents use it to fill `drivers`.

### 3.2 agent_registry.py

- `register(root: Path, agent_id, kind, port, frame_slot, pid=None) -> Path` writes
  `root/"runs"/"agents"/f"{agent_id}.json"` atomically (write `.tmp`, `os.replace`) with
  `{id, kind, pid (default os.getpid()), port, frame_slot, started (time.time())}`.
- `unregister(root, agent_id)` removes it (missing file is fine).
- `list_agents(root) -> list[dict]` reads every `*.json`, skips unreadable ones, and drops entries whose pid is
  not alive. Reuse `pokeagent.registry.process_alive(pid)` (it exists; Windows `OpenProcess` +
  `GetExitCodeProcess == 259`). Sorted by `id`.
- `runs/` is gitignored; tests use `tmp_path`.

### 3.3 control_server.py

`ControlServer(snapshot_fn: Callable[[], AgentSnapshot], handlers: dict[str, Callable[..., dict]],
host="127.0.0.1", port=0)` - `start()` runs a `ThreadingHTTPServer` on a daemon thread and returns the bound
port; `stop()` shuts it down. `GET /snapshot` -> 200 JSON `snapshot_fn().to_dict()`. `POST /command` with JSON
`{"cmd": name, ...args}` -> calls `handlers[name](**args)` and returns its dict merged with `{"ok": true}`;
unknown cmd -> 400 `{"ok": false, "error": "unknown command <name>"}`; handler exception -> 500
`{"ok": false, "error": str(exc)}`; bad JSON -> 400. Command names v1 (constants in the module):
`pause, resume, speed (n:int 1|2|4|8), press (button: A|B|START|SELECT|UP|DOWN|LEFT|RIGHT), steer (on: bool),
hand_to (driver), save_state (name), load_state (name)`. The server validates arg presence/type for these and
returns 400 on a bad arg before calling the handler. Silence the default request logging.

### 3.4 viewer/ (pure)

- `sources.py`: `class AgentSource(Protocol): agent_id; def snapshot() -> AgentSnapshot | None;
  def frame() -> tuple[bytes, int, int] | None; def send(cmd: str, **args) -> dict`.
  `HttpShmSource(entry: dict)` (an `agent_registry` entry): `urllib.request` with a 0.5 s timeout for
  `/snapshot` and `/command`; any network error returns `None` / `{"ok": False, "error": ...}` - never raises;
  frames via `FrameSubscriber(entry["frame_slot"] id)`. `FakeSource(agent_id, snapshots, frames)` replays given
  lists and records sent commands (for tests and for V2's offline mode).
  `discover(root) -> list[HttpShmSource]` from `agent_registry.list_agents`.
- `model.py`: `ViewerModel` holds the latest snapshot, frame, and `last_ok` time per agent.
  `poll(sources)` reads each source once (this is what V2's background thread calls); `staleness(id, now)` ->
  `"live"` (< 2 s), `"stale"` (2-10 s), `"lost"` (> 10 s). Thread-safe: one `threading.Lock`, readers get copies.
- `layout.py`: `grid(n: int, width: int, height: int, aspect=(10, 9)) -> (cols, rows, card_w, card_h)` choosing
  the column count that maximises card area for n cards (n = 0..12; a card is a frame of `aspect` plus a text
  area equal to its width); `FocusState` with `focus(id)`, `back()`, `toggle(id)` (double-click semantics:
  focusing the focused card returns to multi-view), `.focused -> str | None`.
- `commands.py`: `KEYMAP = {"Up": "UP", "Down": "DOWN", "Left": "LEFT", "Right": "RIGHT", "a": "A", "s": "B",
  "Return": "START", "Shift_L": "SELECT", "Shift_R": "SELECT"}`; `press_for_key(key, steer_on) -> str | None`
  (None when steer is off); `targets(selected, all_ids, scope)` (scope "selected" | "all"); `SPEEDS = (1, 2, 4, 8)`;
  `next_speed(cur)`.

### 3.5 Human hold (auto-pause on human input; Robert 2026-11-05)

Robert: when he steers, the agent should stop deciding so they don't fight each other; his input is
"interference, noise", not ground truth. `src/pokeagent/human_hold.py`: `HumanHold(idle_s: float = 3.0,
clock=time.monotonic)` with `.touch()` (called on every human `press`), `.active() -> bool` (True until `idle_s`
after the last touch), `.release()` (immediate). Agents check `active()` before each own decision and skip
deciding while it is True (the game keeps running; only the agent's choices pause). Add
`human_hold: bool = False` to `AgentSnapshot`. In `control_server.py`, a `press` command carries an optional
`source` (default `"human"`); document in the module docstring that agents must call `HumanHold.touch()` for
`source == "human"` presses. Add `hold_release` to the v1 command names (no args). Tests: active right after
touch, inactive after `idle_s` with an injected clock, a second touch extends it, `release` ends it.

## 4. What NOT to do

- Do not import or add Dear PyGui code (V2 does that). `dearpygui` is already in `pyproject.toml`; leave it.
- Do not change `tools/explore_demo.py`, `tools/rl_train.py`, `tools/watch.py`, `tools/agent_window.py`,
  `tools/webview.py`, or `telemetry.py`'s wire format. Adapters for existing agents come in V2.
- No new dependencies. stdlib + what is already in `uv.lock`.
- No module over 250 lines. Layer rule: `snapshot`, `agent_registry`, `control_server` import nothing from
  `viewer/`; `viewer/` may import them and `telemetry`, `registry`.

## 5. Verification

- `uv run pytest -q` green (178 passed, 5 skipped before this directive; expect that plus your new tests).
- New tests at least: snapshot round-trip `from_dict(to_dict(x)) == x`; unknown keys ignored; missing optional
  keys default; `v=2` raises; `recent` truncated to 20; `DriverWindow` counts after 150 adds. Registry: register
  -> list -> unregister in `tmp_path`; a dead pid (use a pid you spawn and wait for: `subprocess.Popen([sys.executable,
  "-c", "pass"]).wait()`) is dropped. Control server on `port=0`: GET /snapshot JSON; each command reaches its
  handler with typed args; unknown cmd 400; bad arg 400; handler exception 500. `HttpShmSource` against a live
  `ControlServer` returns a snapshot; against a closed port returns `None` within 1 s. `ViewerModel` staleness
  transitions with an injected clock. `grid` for n = 1, 4, 6, 12 at 1920x1000 returns cols 1, 2, 3, 4 (or a
  justified better area - assert area is maximal over all col counts). `FocusState.toggle` semantics.
- Do NOT run `uv run pokeagent ...` (the sandbox refuses the console entry point and the run dies).

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-viewer-core-directive`. Never commit to `main`, never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] `snapshot.py`, `agent_registry.py`, `control_server.py` as in 3.1-3.3
- [ ] `viewer/__init__.py`, `sources.py`, `model.py`, `layout.py`, `commands.py` as in 3.4
- [ ] `human_hold.py`, `human_hold` snapshot field and `hold_release` command as in 3.5
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Every new module under 250 lines (paste `wc -l` or equivalent)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, the grid column counts your `grid` returns for n = 1..12 at 1920x1000, and anything in
section 3 you had to interpret.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | claude |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-09 20:24 · agentflow-tick · none → Queued — suggested by heartbeat: Reconcile only: deliverables exist and V2 cites V1 (#26) as merged; verify and mark Done, do not rebuild.
<!-- queue:end -->
