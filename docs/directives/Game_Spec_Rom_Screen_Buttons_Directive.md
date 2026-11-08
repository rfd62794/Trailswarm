# PokeAgent: ROM default, screen size and button set come from the GameSpec - still Red only, no behaviour change (plan phase 3)

## Why this exists

Phase 3 of `docs/plans/Multi_Game_Framework_Plan.md` (branch `feat/watch-mario-land`, PR #169): "ROM defaults, screen size and button set come from the spec". Phase 2 (`Game_Spec_Package_Directive.md`) created `src/pokeagent/game/` with `GameSpec(key, title, rom_sha1)`, `RED`, `GAMES`, `resolve_game`. This directive widens the spec by exactly three fields and replaces the Red literals scattered through `src/` with reads from it. Rule that governs it: Pokemon Red behaviour stays byte-identical by default; every Red path and size resolves to exactly the value it has today.

**Depends on `Game_Spec_Package_Directive.md` being merged.** Start from a main that contains `src/pokeagent/game/spec.py`. If `git grep -n "class GameSpec" -- src` finds nothing at the start of the run, stop and write that in the Status row; do not recreate phase 2.

Measured on main 2026-11-08:

- The ROM path literal `Pokemon Red.gb` appears in 12 source files: `src/pokeagent/atlas/collision.py` (:26, :51 as defaults), `atlas/ladders.py` (:10), `atlas/rom_maps.py` (:23, :119), `atlas/walkgrid.py` (:82, :116), `cli.py` (:32 `DEFAULT_ROM`), `invariants/runner.py` (:13), `knowledge/hm_compat.py` (:14 `ROM_PATH = ROOT / "roms" / "Pokemon Red.gb"`), `knowledge/items_catalog.py` (:24 same shape), `legs/grid.py` (:75-77), `statescmd.py` (:19 `DEFAULT_ROM`), `world/app.py` (:46 `--rom` default), `world/export.py`. The 40-odd `tools/` scripts and the tests also use it; those are Red-specific scripts and tests and are NOT in this phase.
- Screen size `160 x 144` is hard-coded in `src/pokeagent/emulator.py:13` (`_SCREEN_SIZE`, used at :186 and :192 by the fake emulator), `src/pokeagent/telemetry.py:28` (`FRAME_W, FRAME_H`, used for the shared-memory frame slot size at :53, :105, :123, :131-133, and as the fallback at :195-196 when the slot header carries no size), `src/pokeagent/pixelsig.py:17-20` (`width: int = 160`, `144`), and `src/pokeagent/viewer/app.py:72` (`w, h = 160, 144`).
- The button set is the `Button` StrEnum in `emulator.py:16-26`: UP DOWN LEFT RIGHT A B START SELECT plus NONE. `press()` (`PyBoyEmulator` :93, `FakeEmulator` :171) accepts any member; nothing says which a game has.
- `tests/test_frame_slots.py` and `tests/test_emulator.py` are the pins for the screen size and button behaviour.

Read first: `src/pokeagent/game/*.py` (from phase 2), `src/pokeagent/emulator.py` (whole file, 204 lines), `src/pokeagent/telemetry.py` lines 20-135 and 185-200, `src/pokeagent/pixelsig.py` lines 1-30, `tests/test_frame_slots.py`, `tests/test_emulator.py`.

## Scope (in this order)

1. `src/pokeagent/game/spec.py` - add three fields.
2. `src/pokeagent/game/pokemon_red.py` - fill them with Red's current values.
3. `src/pokeagent/game/paths.py` <!-- new: src/pokeagent/game/paths.py --> - `default_rom(game=None) -> Path`, the single place that turns the selected game into a ROM path. Under 40 lines.
4. `src/pokeagent/emulator.py` - the emulators take a `game` and use its screen size and button set.
5. `src/pokeagent/telemetry.py`, `src/pokeagent/pixelsig.py`, `src/pokeagent/viewer/app.py` - read the frame size from the spec instead of the literal.
6. The ROM-path files in `src/` listed above: `src/pokeagent/cli.py`, `src/pokeagent/statescmd.py`, `src/pokeagent/atlas/collision.py`, `src/pokeagent/atlas/ladders.py`, `src/pokeagent/atlas/rom_maps.py`, `src/pokeagent/atlas/walkgrid.py`, `src/pokeagent/invariants/runner.py`, `src/pokeagent/knowledge/hm_compat.py`, `src/pokeagent/knowledge/items_catalog.py`, `src/pokeagent/legs/grid.py`, `src/pokeagent/world/app.py`, `src/pokeagent/world/export.py` - replace the literal by the spec's path.
7. Tests, listed in the completion criteria.
8. `docs/KNOWLEDGE.md` - extend the GameSpec paragraph with the three fields.

## The work

### Spec fields (spec.py, pokemon_red.py)

Add to `GameSpec`, after `rom_sha1`, without defaults (every spec must say them):

```
default_rom: Path                    # relative to the repo root, forward slashes, e.g. Path("roms/Pokemon Red.gb")
screen: tuple[int, int]              # (width, height) in pixels
buttons: tuple[str, ...]             # lowercase names of the buttons the game uses, in this order
```

Validation in `__post_init__`: `default_rom` is relative (not absolute) and has a suffix; `screen` is two positive ints; `buttons` is non-empty, unique, lowercase, and a subset of `{"up","down","left","right","a","b","start","select"}` (the pad this emulator layer knows; a game with another pad extends that set in its own directive). RED: `default_rom=Path("roms/Pokemon Red.gb")`, `screen=(160, 144)`, `buttons=("up","down","left","right","a","b","start","select")`. `game/` must not import `pokeagent.emulator` (the emulator imports `game`; a cycle would break). Buttons are plain strings that equal `Button` values for exactly this reason.

### paths.py

`default_rom(game: GameSpec | None = None, root: Path | None = None) -> Path`: with no `game` it uses `resolve_game(None)` (so `POKEAGENT_GAME` is honoured); returns `game.default_rom` if `root` is None, else `root / game.default_rom`. For Red the result must `==` the `Path` each caller built before (`Path("roms/Pokemon Red.gb")`, or `ROOT / "roms" / "Pokemon Red.gb"`); a test asserts this per caller. This function does not look at `$POKEAGENT_ROM`: `cli._rom_path` keeps its precedence (`--rom`, then `$POKEAGENT_ROM`, then `default_rom()`).

### emulator.py

- `PyBoyEmulator.__init__` and `FakeEmulator.__init__` gain an optional keyword `game: GameSpec = RED` (import `RED` from `pokeagent.game.pokemon_red`). Existing call sites pass nothing and are unchanged.
- `screen_size` property on both, returning `game.screen`. `_SCREEN_SIZE` is deleted; `FakeEmulator.frame_image`/`frame_rgb` (:186, :192) use the instance's size. The docstring "144*160*3 RGB bytes" at :136 becomes size-neutral wording.
- `press(button, ...)`: if `button is not Button.NONE` and `button.value not in self.game.buttons`, raise `ValueError(f"{button.value!r} is not a button of {game.key}")`. For Red this branch can never be reached (all eight are in the set), and a test proves every member of `Button` except `NONE` is accepted by a Red emulator.
- The `Emulator` protocol (:~30) gains `screen_size` only if it is already the pattern for properties there; otherwise leave the protocol alone and say so in the Report.
- The `Button` enum itself is unchanged.

### telemetry.py, pixelsig.py, viewer/app.py

- `FRAME_W, FRAME_H = RED.screen` as module defaults (keep both names exported so existing imports work). `FramePublisher` takes the slot size from the emulator it is given (`emu.screen_size` when present, else the defaults) and writes it in the existing header fields; the subscriber already reads width and height from the header with `FRAME_W`/`FRAME_H` as the fallback (:195-196): keep that fallback. The header layout version, the header size and every offset stay exactly as they are (the `reader_ts` field and `LAYOUT = 2` from the viewer pull model are not touched). For a Red emulator the slot is byte-identical to today's.
- `pixelsig.py`: the width and height defaults come from `RED.screen`; the function signatures keep their parameters and their results for 160x144 input are unchanged.
- `viewer/app.py:72`: `w, h = RED.screen` as the fallback value.
- If any of these files would grow past 300 lines, split a helper out rather than exceed it (`explorer/context.py` and `explorer/memory.py` are already at 299: do not touch them).

### ROM-path files

In each of the twelve source files, replace `Path("roms/Pokemon Red.gb")` or `ROOT / "roms" / "Pokemon Red.gb"` with `default_rom()` or `default_rom(root=ROOT)` (or `RED.default_rom` where a module-level constant is needed at import time and `POKEAGENT_GAME` must not change it; say which in a comment). Keep every public name that exists today (`DEFAULT_ROM`, `ROM_PATH`, `KB_PATH`): they are just assigned from the spec. Where the literal is in a function default argument (`rom_path: str = "roms/Pokemon Red.gb"`), keep the parameter and make the default `str(RED.default_rom).replace("\\", "/")`-equivalent, so `inspect.signature` default is still the exact same string. Docstrings and `--rom` help text that name the file are reworded to say "the game's ROM" so the grep criterion can be exact.

## What NOT to do

- Do not touch `roms/`, `baselines/`, or any ROM data, and do not state where any game copy came from.
- Do not add a second game, or a Blue, Mario or Wario spec. Only `RED` exists after this phase.
- Do not change any `runs/` or `kb/` store path, `statemeta.py`, state sidecars, or anything in phase 4's scope.
- Do not add real-time input, held buttons, or a chord API (plan phase 5). `press()` semantics (hold then settle) stay exactly as they are.
- Do not edit anything in `tools/` or the existing tests that use the literal, except where a test asserts the old module-level name and breaks: edit such a test minimally and list it in the Report.
- Do not rename `Button`, change the telemetry header layout, or alter the `world` view's drawing code (only its `--rom` default and ROM path read in `world/app.py` and `world/export.py`).
- No new dependency, no scratch or debug files outside `.devin-scratch/`, no file over 300 lines.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_frame_slots.py tests/test_emulator.py tests/test_cli.py tests/test_game_spec.py tests/test_game_paths.py tests/test_emulator_game.py tests/test_game_frame_size.py tests/test_rom_default_callers.py
```
Expected: all pass.

```
git grep -n "Pokemon Red.gb" -- src
```
Expected: exactly one hit, in `src/pokeagent/game/pokemon_red.py`.

```
git grep -nE -e "\b160\b.{0,12}\b144\b" -e "\b144\b.{0,12}\b160\b" -e "_SCREEN_SIZE" -- src
```
Expected: the hits are only in `src/pokeagent/game/pokemon_red.py` (and unrelated 160 uses such as text slices `[:160]` or `_BOX_WAIT = 160`, which are not screen sizes and stay).

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree.

## What the Claude verify lane must run afterwards, with the ROM

A Devin worktree has no ROM and no baselines (`roms/` and `baselines/` are gitignored), so every ROM-gated test skips there and a green Devin run proves nothing about real emulation. Claude runs in a fresh worktree of the PR head with `roms/` and `baselines/` junctioned in:

1. `uv run pytest -q tests/test_golden_red.py`. This is the gate: a changed hash rejects the PR. It skips in a dispatch worktree because the ROM and baselines are absent; report it as NOT run, not as passed. Claude's ROM-present check runs it before merge. The recorded hash must not change (a deliberate change re-records it from a base-commit run in the same PR). The test relies on the default `roms/Pokemon Red.gb` path, so keep that default for Red.
2. `uv run pytest -q` with the ROM present: the passed and skipped counts equal base, in particular `tests/test_frame_slots.py`, `tests/test_emulator.py`, `tests/test_atlas_rom.py`, `tests/test_walkgrid.py`, `tests/test_world_view.py`.
3. `uv run pokeagent check-rom` output equals the base commit's, byte for byte.
4. A viewer-side spot check that a published frame slot is the same size as before: `uv run pytest -q tests/test_frame_slots.py` with the ROM, plus one `pokeagent world --png out.png --scale 0.25` run compared pixel-for-pixel with the base commit's output (the ROM-path edits in `world/` must not change the render).

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Branch only (`directive/pokeagent-game-spec-rom-screen-buttons-directive`); commit as you go; never commit to or push main; never merge.
- Tests are headless and need no ROM: use `FakeEmulator`, synthetic fake `GameSpec` instances built in the test (for example a 2x2 screen, a three-button pad), and `tmp_path`. Nothing may open a window.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and the two grep outputs in the Report.

## Completion criteria

- [ ] `GameSpec` validation: relative `default_rom`, positive two-int `screen`, non-empty unique lowercase `buttons` within the known pad; RED carries exactly today's values. <!-- test: tests/test_game_spec.py -->
- [ ] `default_rom()` equals `Path("roms/Pokemon Red.gb")` for Red, honours `POKEAGENT_GAME` (an unknown key fails the same way `resolve_game` does), and `default_rom(root=r)` equals `r / "roms" / "Pokemon Red.gb"`. <!-- test: tests/test_game_paths.py --> <!-- new: tests/test_game_paths.py -->
- [ ] Each of the twelve caller modules resolves to the same path value as before (assert per module: `cli.DEFAULT_ROM`, `statescmd.DEFAULT_ROM`, `hm_compat.ROM_PATH`, `items_catalog.ROM_PATH`, the default parameter strings of `atlas.collision.rom_tile_pairs`, `rom_walkable_ids`, `atlas.ladders.rom_ladders`, `atlas.walkgrid.rom_planner`, `rom_cave_planner`, `atlas.rom_maps.load`, `valid_map_ids` via `inspect.signature`), and `cli._rom_path` precedence (`--rom`, `$POKEAGENT_ROM`, default) is unchanged. <!-- test: tests/test_rom_default_callers.py --> <!-- new: tests/test_rom_default_callers.py -->
- [ ] A Red `FakeEmulator` reports `screen_size == (160, 144)` and returns frames of that size; a fake `GameSpec` with a 2x2 screen and three buttons makes `FakeEmulator(game=...)` return 2x2 frames, accept its three buttons and raise `ValueError` for a fourth; every `Button` member except `NONE` is accepted by a Red emulator. <!-- test: tests/test_emulator_game.py --> <!-- new: tests/test_emulator_game.py -->
- [ ] A frame slot published for a 2x2 fake game round-trips through `FramePublisher`/`FrameSubscriber` with the right width and height, and a Red slot has the same total size and header bytes as before (compare against the layout constants, not a stored fixture). <!-- test: tests/test_game_frame_size.py --> <!-- new: tests/test_game_frame_size.py -->
- [ ] The existing frame-slot and emulator tests pass without edits. <!-- test: tests/test_frame_slots.py -->
- [ ] The existing CLI tests pass without edits (the single edit made in phase 2 stays). <!-- test: tests/test_cli.py -->
- [ ] The two `git grep` checks above give the stated results.
- [ ] No file in `src/` over 300 lines is touched except by a reduction; `git diff --stat main` touches only the files in Scope plus tests and docs.
- [ ] Status row set to `Review` with the evidence above and the "Claude verify lane" section copied into the Status note.

## Report

Diff stat, test tails, both grep outputs, the new files' line counts, which module-level names kept their old name and how each is now assigned, any existing test you had to edit (file and lines), and a plain statement that `tests/test_golden_red.py` (skipped), the ROM-present suite and the `world --png` comparison were NOT run (no ROM in the worktree) and are owed by the Claude verify lane.

## Forbidden Actions

- Do not touch `roms/`, `baselines/` or any ROM data, and do not state where a game copy came from.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not edit `tools/`, `explorer/context.py`, `explorer/memory.py`, `statemeta.py`, or any `runs/`/`kb/` path logic.
- Do not register another game or add real-time input.
- Do not commit to or push main, merge, deploy, or open a window.

## Required from User

- None for the run. The ROM-present checks above are Claude's verify lane, not Robert's.
- Sequencing: do not approve this until `Game_Spec_Package_Directive.md` is merged; `Game_Namespaced_Stores_Directive.md` must not be approved until this one is merged.

## Sandbox needs

- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-game-spec-rom-screen-buttons-directive |
| Base branch | - |
| Base commit | 7c77bd14454c0e360efe5c75a2b8660a54d62404 |

**Status log**
- 2026-11-08 12:16 · robert-claude-laptop · none → Queued — Drafted by Claude: plan phase 3; do not approve before Game_Spec_Package merged
- 2026-11-08 17:55 · robert-claude-laptop · Queued → Approved
- 2026-11-08 18:48 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-game-spec-rom-screen-buttons-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6YS01SP57K82E3R97Q4VVE7
<!-- queue:end -->
