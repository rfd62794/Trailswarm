# PokeAgent: MCP server - `pokeagent mcp` exposes the emulator as tools so Claude or Devin can play directly

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`. Build step 5. Depends on
`Agent_Loop_And_CLI_Directive.md` being merged (`src/pokeagent/cli.py` must exist; you add one subcommand).
If `cli.py`, `emulator.py`, `ram.py`, `backend.py` or `decision.py` is missing from your worktree, stop and
write that in the Status row. **Do not list the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree`
are refused by the sandbox and end the run); use `git ls-files`.

## 1. Why this exists

Robert asked (2026-11-02) whether the framework can "optionally behave like an MCP". Yes: with the emulator
behind an MCP server, a Claude Code session (or Devin) plays Pokemon Red by calling tools - `press`, `state`,
`screenshot`, `peek` - and keeps its own reasoning and memory, instead of the `claude -p` prompt loop. Robert
watches the PyBoy window while the session plays. The `claude -p` loop stays for cheap unattended runs.

Verified facts (laptop, 2026-11-02):
- `mcp==2.3.0` is already in `uv.lock` (added by the controller; do not run `uv add`). It is the 2.x SDK:
  `from mcp.server.mcpserver import MCPServer` (FastMCP was renamed). `MCPServer("name")`,
  `@server.tool()` on plain typed functions (docstring becomes the description), `@server.resource(uri)`,
  `server.run(transport="stdio")`. `from mcp.server.mcpserver import Image` wraps image bytes for a tool
  result: `Image(data=png_bytes, format="png")`.
- Test command `uv run pytest -q` (Python 3.12.12). No ROM in your worktree; all tests use `FakeEmulator`.
- A stdio MCP server owns stdout. Nothing in the server may `print()` to stdout; log to stderr only.
- SDL2 windows must be created and ticked on one thread, and Windows marks a window "not responding" if
  its event loop stalls for a few seconds. So the emulator lives on its own thread that ticks continuously
  and executes commands between frames (section 3).
- A baseline state exists outside git at `baselines/bedroom.state` (gitignored, like `roms/`); the server
  must handle it being absent (clear error, no hunting).

## 2. Scope

Create, in order:

1. `src/pokeagent/emu_thread.py` - `EmulatorThread`: owns the emulator, ticks it, runs posted commands.
2. `src/pokeagent/mcp_server.py` - `build_server(thread) -> MCPServer` with the tools below, plus `serve(...)`.
3. `pokeagent mcp [--rom PATH] [--state PATH] [--headless] [--idle-fps 60]` subcommand in `cli.py`
   (implementation in `mcp_server.py`; `cli.py` only registers the subparser).
4. `.mcp.json` at the repo root (so a Claude Code session opened in the repo gets the tools):

   ```json
   {"mcpServers": {"pokeagent": {"command": "uv", "args": ["run", "pokeagent", "mcp", "--state", "baselines/bedroom.state"]}}}
   ```

5. `tests/test_emu_thread.py`, `tests/test_mcp_server.py`; a short "Play it from Claude Code" section in `README.md`.
6. Demo integration: expose the rule-based explorer policy (tools/explore_demo.py) as an MCP tool `explore(steps: int)` that runs N explorer steps on the emulator thread and returns the map-memory summary, so a Claude session can hand control to the explorer and take it back.

## 3. The work

### `emu_thread.py`

```python
class EmulatorThread:
    def __init__(self, factory: Callable[[], Emulator], *, idle_fps: int = 60): ...
    def start(self) -> None          # creates the emulator INSIDE the thread via factory, then loops
    def call(self, fn: Callable[[Emulator], T], timeout: float = 30) -> T   # post fn, block for its result
    def stop(self) -> None           # drains, closes the emulator on the thread, joins
```

Loop body: pop every queued command and run it (`fn(emu)`, result or exception handed back through a
`Future`); if `paused` is False, `emu.tick(1)` and sleep to hold `idle_fps` (0 = no idle ticking: the game
only advances inside commands). Exceptions inside `fn` propagate to the caller of `call`, never kill the
thread. Any exception from the factory is re-raised by `start()`.

### `mcp_server.py` tools (every tool runs through `thread.call`; return plain dicts/strings unless noted)

| tool | args | returns |
|---|---|---|
| `press` | `button: str`, `repeat: int = 1`, `hold_frames: int = 8`, `settle_frames: int = 16` | the new `state()` dict; unknown button -> `{"error": "..."}` |
| `wait` | `frames: int = 60` | `state()` |
| `state` | - | `read_state(emu).as_dict()` plus `"summary"` |
| `screenshot` | `scale: int = 1` | `Image` (PNG, 160x144 * scale, nearest-neighbour) |
| `peek` | `addr: int`, `length: int = 1` | `{"addr": "0xD362", "hex": "03", "bytes": [3]}`; refuse length > 4096 |
| `snapshot` | `name: str` | stores WRAM `0xC000-0xDFFF` under `name` in memory; returns byte count |
| `diff` | `a: str`, `b: str`, `limit: int = 200` | changed bytes between two snapshots, `[{"addr": "0x....", "old": .., "new": ..}]`, with `RAM_MAP` names where known |
| `save_state` | `name: str` | writes `runs/mcp/<name>.state` (name sanitised to `[A-Za-z0-9_-]`); returns the path |
| `load_state` | `name_or_path: str` | loads `runs/mcp/<name>.state`, or an existing path under the repo; absent -> `{"error": "..."}` |
| `pause` / `resume` | - | toggles idle ticking; returns `{"paused": bool}` |
| `note` | `text: str` | appends to `runs/mcp/notes.txt`; returns the last 20 lines |

Also one resource: `pokeagent://state` returning the `state()` dict as JSON, for clients that read resources.

`serve(rom: Path, state: Path | None, headless: bool, idle_fps: int)`: factory builds
`PyBoyEmulator(rom, headless=headless)`, ticks 60, loads `state` if given (missing file -> exit 2 with a
stderr message); starts the thread; `server.run(transport="stdio")`; stops the thread in `finally`.

### `cli.py`

Register `mcp` with the arguments above; ROM default as in `run`. The subcommand never prints to stdout.

## 4. What NOT to do

- No `print()` to stdout anywhere on the server path; no `uv add`; no change to `pyproject.toml` or `uv.lock`.
- Do not touch `emulator.py`, `ram.py`, `backend.py`, `decision.py`, `agent.py`.
- Do not open an SDL2 window in tests; do not call the real ROM; do not read outside the worktree.
- Do not add vision/OCR; `screenshot` returns pixels only.
- Do not implement a network transport; stdio only.

## 5. Verification

- `uv run pytest -q` green. New tests at least: `EmulatorThread` runs a command on its own thread
  (compare `threading.get_ident()`), returns results, propagates exceptions, idle-ticks when `idle_fps > 0`
  and not when 0, `pause` stops ticking, `stop` closes the fake exactly once; every tool through the server
  built on a `FakeEmulator` thread: `press` records presses and returns state, `peek` hex formatting and the
  4096 refusal, `snapshot`/`diff` on a scripted change, `save_state`/`load_state` round-trip in `tmp_path`,
  unknown button and missing state return `error` dicts, `note` appends.
- Tool invocation in tests: call the registered tool functions directly (the decorator returns the
  function unchanged), or use the SDK's in-memory client if it is simple; do not spawn a subprocess.
- Do NOT run `uv run pokeagent ...` yourself: the sandbox refuses the console entry point and the run dies (it killed two earlier runs at exactly this step). Test the argparse wiring with `uv run python -c "from pokeagent.cli import main; main(['mcp', '--help'])"` instead; the controller runs the real command.
- Controller check (not yours): open Claude Code in the repo; the `pokeagent` server appears; `state` returns
  the bedroom; `press RIGHT` changes x.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-mcp-server-directive`. Never commit to `main`, never push to it,
  never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 250 lines.

## 7. Completion criteria

- [ ] `emu_thread.py` with `EmulatorThread` (start, call, stop, pause flag, idle ticking)
- [ ] `mcp_server.py` with the 12 tools and the `pokeagent://state` resource; `pokeagent mcp` subcommand
- [ ] `.mcp.json` at the repo root
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] README section "Play it from Claude Code"
- [ ] Demo integration (section 2 item 6): MCP tool `explore(steps: int)` runs explorer steps on the emulator thread and returns the map-memory summary
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, and any place the mcp 2.x API differed from section 1 (say exactly what you used).

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-mcp-server-directive |
| Base branch | - |
| Base commit | d2184fc4a4b66d6a3e3b4c0ae01dc3048eb8ff5f |
| Head commit | 6b3a70e15bdee7fa8095d672289f1e145711a204 |
| Head remote | rfd62794/pokeagent |

**Status log**
- 2026-11-02 22:25 · robert-claude-laptop · none → Draft — build step 5 (MCP server), Robert asked 2026-11-02; mcp==2.3.0 already in uv.lock; queue after Agent_Loop_And_CLI merges
- 2026-11-02 22:37 · robert-claude-laptop · Draft → Queued — prereq Agent_Loop_And_CLI merged (PR #4); mcp 2.3.0 in uv.lock via PR #5
- 2026-11-02 23:15 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: the cited new paths are files it creates; dispatch-path-missing is a false positive
- 2026-11-02 23:15 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-mcp-server-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6FSXVCY8FDNF0BCCTF8YW9T
- 2026-11-02 23:18 · dispatcher · launched pid=27932; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-mcp-server-directive; provisioned: uv sync --frozen
- 2026-11-02 23:26 · devin-overseer (delegated) · In progress → Review — under delegate.envelope [origin] spent: devin 6 min est. n/a
<!-- queue:end -->
