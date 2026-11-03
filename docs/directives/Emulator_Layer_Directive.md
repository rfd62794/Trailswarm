# PokeAgent: emulator layer - `Emulator` protocol, `PyBoyEmulator`, `FakeEmulator`, RAM state reader

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md` (the design; this directive is build step 1 of 3).

## 1. Why this exists

PokeAgent is an agent that plays Pokemon Red on its own through PyBoy, in a window Robert can watch. Nothing in
`src/pokeagent/` exists yet beyond `__init__.py`. The agent loop (directive 3) needs a thin emulator seam it can
drive with a fake in tests and PyBoy in real runs, plus a typed reading of the game's RAM. This directive builds
that seam.

Verified on the laptop 2026-11-02 (`uv run python --version` -> `Python 3.12.12`; `pyboy==2.9.0`, `pillow==13.0.0`,
`pysdl2-dll==2.32.10`, `pytest==9.2.0` all already in `uv.lock`; `uv run pytest -q` -> `1 passed`). PyBoy 2.9 API
as exercised on the real ROM:

```python
from pyboy import PyBoy
p = PyBoy("roms/Pokemon Red.gb", window="null")   # "null" = headless; "SDL2" = visible window
p.set_emulation_speed(0)                           # 0 = unthrottled, 1 = real time
p.tick(60, False)                                  # (frames, render)
p.memory[0xD35E]                                   # int read; p.memory[a:b] returns a list
p.button("a", 8)                                   # press for 8 frames; names: a b start select up down left right
p.screen.image                                     # PIL Image, size (160, 144)
import io; b = io.BytesIO(); p.save_state(b)       # 178108 bytes; load_state(b) after b.seek(0)
p.stop(save=False)
```

The ROM is NOT in your worktree (`roms/` is gitignored). Every test in this directive must pass without it.

## 2. Scope

Create, in order:

1. `src/pokeagent/emulator.py` - `Button` (StrEnum: `UP DOWN LEFT RIGHT A B START SELECT NONE`), `Emulator`
   (`typing.Protocol`), `PyBoyEmulator`, `FakeEmulator`.
2. `src/pokeagent/ram.py` - `RAM_MAP`, `GameState`, `read_state(emu) -> GameState`, `decode_bcd(bytes) -> int`.
3. `tests/test_emulator.py`, `tests/test_ram.py`, `tests/test_real_rom.py`.

## 3. The work

### `emulator.py`

`Emulator` protocol methods:

- `press(button: Button, hold_frames: int = 8, settle_frames: int = 16) -> None` - `NONE` only ticks
  `hold_frames + settle_frames`.
- `tick(frames: int) -> None`
- `read(addr: int) -> int` and `read_range(start: int, length: int) -> bytes`
- `screenshot() -> PIL.Image.Image` (160x144 RGB)
- `save_state(path: Path) -> None`, `load_state(path: Path) -> None`
- `close() -> None`

`PyBoyEmulator(rom_path: Path, *, headless: bool = True)`: constructor raises `FileNotFoundError` naming the path
if the ROM is missing (do not search for it elsewhere). `headless=True` -> `window="null"`, speed 0;
`headless=False` -> `window="SDL2"`, speed 1 (real time, so a watcher sees normal-speed movement). `tick(n, render)`
passes `render=not headless`. `press` maps `Button` to PyBoy's lowercase names via `button(name, hold_frames)`
then ticks `settle_frames`. `save_state`/`load_state` open the path in binary mode. `close` calls
`stop(save=False)`; make it idempotent.

`FakeEmulator(memory: dict[int, int] | None = None)`: an in-memory dict defaulting unset bytes to 0; `presses:
list[Button]` and `frames: int` record what happened; `set(addr, value)` lets tests script state; `screenshot`
returns `Image.new("RGB", (160, 144))`; `save_state` writes the memory dict as JSON, `load_state` reads it.

### `ram.py`

```python
RAM_MAP = {   # believed addresses from pret/pokered wram.asm - UNVERIFIED, calibrated later; keep in this one table
    "map_id": 0xD35E, "player_y": 0xD361, "player_x": 0xD362, "party_count": 0xD163,
    "badges": 0xD356, "in_battle": 0xD057, "money": 0xD347,   # money: 3 bytes BCD
}
```

`GameState` is a frozen dataclass: `map_id:int, x:int, y:int, party_count:int, badges:int, badge_count:int,
in_battle:bool, money:int`. `badge_count = bin(badges).count("1")`. `in_battle = read(0xD057) != 0`.
`decode_bcd(b"\x01\x23\x45") == 12345`. `read_state` reads only through the `Emulator` protocol. Add
`GameState.as_dict()` (plain dict for JSON logging) and `GameState.summary()` (one line:
`map=0x26 pos=(3,6) party=1 badges=0 battle=no money=3000`).

## 4. What NOT to do

- Do not write the agent loop, backend, prompt, console, CLI or run logging. Those are directives 2 and 3.
- Do not add dependencies or edit `pyproject.toml` / `uv.lock`.
- Do not add stuck detection, pathing, or tile-map reading.
- Do not "fix" the RAM addresses; they are deliberately marked unverified.
- Do not open an SDL2 window in any test (CI has no display); tests use `FakeEmulator` only.
- Do not look for the ROM, download anything, or read outside the worktree.

## 5. Verification

- `uv run pytest -q` -> all green, at least 12 tests, no ROM needed. Include: `FakeEmulator` records presses
  and frame counts; `NONE` ticks without pressing; `decode_bcd` on three cases; `read_state` on a scripted fake
  returns the expected `GameState` including `badge_count` and `in_battle`; `save_state`/`load_state` round-trips
  the fake; `PyBoyEmulator(Path("nope.gb"))` raises `FileNotFoundError`; `summary()` format.
- `tests/test_real_rom.py`: one test marked `@pytest.mark.skipif(not os.environ.get("POKEAGENT_ROM")
  or not Path(os.environ["POKEAGENT_ROM"]).exists(), reason="no ROM")` that boots `PyBoyEmulator(headless=True)`,
  ticks 60, calls `read_state`, screenshots (asserts size 160x144), and closes. It skips in your run; the
  controller runs it with the ROM.
- `uv run python -c "import pokeagent.emulator, pokeagent.ram"` -> no output, exit 0.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-emulator-layer-directive`. Never commit to `main`, never push to
  it, never merge. Only Claude or Robert merges.
- Create no scratch or debug files. If one is unavoidable it goes under `.devin-scratch/` and stays.
- Keep every new module under 300 lines.

## 7. Completion criteria

- [ ] `emulator.py` with `Button`, `Emulator`, `PyBoyEmulator` (headless flag), `FakeEmulator`
- [ ] `ram.py` with `RAM_MAP`, `GameState`, `read_state`, `decode_bcd`
- [ ] `tests/test_emulator.py`, `tests/test_ram.py`, `tests/test_real_rom.py` (skips without ROM)
- [ ] `uv run pytest -q` green (paste the tail in the report)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts per new file, and anything in the design you had to decide that is not written down.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-02 21:54 · robert-claude-laptop · none → Queued — build step 1 of 3; design at docs/superpowers/specs/2026-11-02-pokeagent-design.md; independent of step 2
- 2026-11-02 21:54 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: the cited paths are the files it creates (section 2 says Create), not files it reads; dispatch-path-missing is a false positive here
<!-- queue:end -->
