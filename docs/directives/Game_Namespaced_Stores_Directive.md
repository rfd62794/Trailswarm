# PokeAgent: namespace the shared stores by game, record the game in state sidecars, refuse a mismatched state load - Red keeps today's paths (plan phase 4)

## Why this exists

Phase 4 of `docs/plans/Multi_Game_Framework_Plan.md` (branch `feat/watch-mario-land`, PR #169): "Namespace `runs/` and `kb/` by game, with Red on today's paths; game key in state sidecars; refuse a mismatched state load". The stop point is "safe for a second game to run". Rule that governs it: Pokemon Red behaviour stays byte-identical by default, Red's paths resolve to where they are today.

**Depends on `Game_Spec_Rom_Screen_Buttons_Directive.md` being merged** (which depends on `Game_Spec_Package_Directive.md`). Start from a main containing `src/pokeagent/game/paths.py` and `GameSpec.default_rom`. If `git grep -n "def default_rom" -- src` finds nothing at the start, stop and write that in the Status row.

Measured on main 2026-11-08 (every store below is shared with no game key; map ids are bare integers, so a second game would silently merge into Red's data):

- `runs/maps.json`: `src/pokeagent/explorer/context.py:33` (`maps_path`), `explorer/legacy.py:26`, `cli_brain.py:22` (`MAPS_DEFAULT`), `mcp_server.py:28` (`MAPS_PATH`), `navigation.py:17` (`load_memory`), `observations.py:33`, `statemeta.py:71` (`tile_snapshot`).
- `runs/bandit.json`: `explorer/context.py:37` (`bandit_path`); the store is `src/pokeagent/bandit/store.py`.
- `runs/novelty.json`: `explorer/context.py:41` (`novelty_path`); the store is `src/pokeagent/novelty/store.py`.
- `runs/checkpoints`: `explorer/press_goals.py:62`, `explorer/press_track.py:53` and `:60`, `statescmd.py:16` (`DEFAULT_DIRS`).
- `kb/*`: `knowledge/hm_compat.py:14`, `knowledge/items_catalog.py:24`, `knowledge/kb.py:7` (`_KB` = `kb/rom_tables.json`), `statescmd.py:31`, `review/swarm.py:111`.
- `explorer/context.py` and `explorer/memory.py` are at 299 lines (ceiling 300, enforced by `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size`): the edits there must not add a line.
- State sidecars: `src/pokeagent/statemeta.py` `StateMeta` (:20-33) has `game: dict` (a RAM snapshot: map_id, x, y, ...) but NO game key. `write_state` (:94) writes it; `read_meta` (:130) reads `StateMeta(**json)`; `load_state` (:125) loads then reads the meta. A Red state would load silently under any other game. `PyBoyEmulator.load_state` is `emulator.py:146`, `FakeEmulator.load_state` is `:200`; callers include `cli.py:83,127`, `cli_hex.py:43`, `mcp_server.py:154,217`, `invariants/states.py:74`, `adapters/explorer_snapshot.py:181`.
- `runs/agents/` (the agent registry), `runs/explore-*` (per-run directories), `runs/swarm`, `runs/segments*` and `runs/legs` are not in the plan's list; they are NOT moved by this directive (the Report lists what a grep finds so a later phase can decide).

Read first: `src/pokeagent/game/*.py`, `src/pokeagent/statemeta.py` (whole file, 150 lines), `src/pokeagent/emulator.py` lines 85-150 and 195-204, `src/pokeagent/bandit/store.py` and `src/pokeagent/novelty/store.py` (their path handling only), `tests/test_statemeta.py`.

## Scope (in this order)

1. `src/pokeagent/game/spec.py` and `src/pokeagent/game/pokemon_red.py` - one new field, `store_namespace`.
2. `src/pokeagent/game/stores.py` <!-- new: src/pokeagent/game/stores.py --> - `store_path(...)`, the single place that maps a store path to a game's path. Under 70 lines.
3. `src/pokeagent/game/state_guard.py` <!-- new: src/pokeagent/game/state_guard.py --> - `check_state_game(path, game)` and `StateGameMismatch`. Under 70 lines.
4. `src/pokeagent/statemeta.py` - `game_key` in `StateMeta`, written by `write_state`.
5. `src/pokeagent/emulator.py` - both `load_state` methods call the guard first.
6. The store call sites: `src/pokeagent/explorer/context.py`, `src/pokeagent/explorer/legacy.py`, `src/pokeagent/explorer/press_goals.py`, `src/pokeagent/explorer/press_track.py`, `src/pokeagent/cli_brain.py`, `src/pokeagent/mcp_server.py`, `src/pokeagent/navigation.py`, `src/pokeagent/observations.py`, `src/pokeagent/statemeta.py`, `src/pokeagent/statescmd.py`, `src/pokeagent/knowledge/hm_compat.py`, `src/pokeagent/knowledge/items_catalog.py`, `src/pokeagent/knowledge/kb.py`, `src/pokeagent/review/swarm.py`.
7. Tests, listed in the completion criteria.
8. `docs/KNOWLEDGE.md` - a paragraph on store namespaces and the state guard.

## The work

### store_namespace (spec.py, pokemon_red.py)

Add `store_namespace: str | None` to `GameSpec` (no default). `None` means "the legacy root": the game's stores live exactly where they do today. RED sets `None`. Any other game would set its own key (for example `"pokemon-blue"`); validation: `None` or equal to `key`. Only RED exists after this phase, so no namespaced game is registered; tests build a fake spec (for example key `"test-game"`, namespace `"test-game"`) to exercise the namespaced branch.

### stores.py

`store_path(rel: str | Path, game: GameSpec | None = None, root: Path | None = None) -> Path`:

- `rel` must start with `runs` or `kb` (a `ValueError` otherwise: the only two namespaced roots).
- Legacy game (`store_namespace is None`): return `rel` unchanged (`Path(rel)`, or `root / rel` when `root` is given). Byte-identical for Red.
- Namespaced game: insert the namespace as the second path component: `runs/maps.json` -> `runs/<ns>/maps.json`, `runs/checkpoints` -> `runs/<ns>/checkpoints`, `kb/items.json` -> `kb/<ns>/items.json`. Never create directories (callers already `mkdir(parents=True)` where they write).
- `game=None` resolves through `resolve_game(None)` so `POKEAGENT_GAME` is honoured.
- `rel` may be given as `str` or `Path`, with `/` or `\`; return a `Path`. Where a call site stores the path as a `str` field (`explorer/context.py` fields `maps_path`, `bandit_path`, `novelty_path`; `cli_brain.MAPS_DEFAULT`), keep the field a `str` equal to `store_path(...).as_posix()` so the value for Red is the identical string `"runs/maps.json"`.

### state_guard.py and statemeta.py

- `StateMeta` gains `game_key: str | None = None` (last field, so older sidecars without it still load through `StateMeta(**data)`). `write_state` sets it from the emulator's game: `getattr(getattr(emu, "game", None), "key", None)`, falling back to `"pokemon-red"` ONLY when the emulator has no `game` attribute at all (the phase 3 emulators always have one; the fallback is for test doubles). Sidecars written for Red now carry `"game_key": "pokemon-red"`; that is the only change to Red's written bytes and the golden trace is not affected (it compares transitions, not sidecars).
- `check_state_game(path: Path, game: GameSpec) -> None`: reads `statemeta.sidecar(path)` if it exists (use `json.loads` directly; do not import `statemeta` here if that creates a cycle: read the one key). Rules:
  - sidecar has `game_key` equal to `game.key`: pass.
  - sidecar has a `game_key` that differs: raise `StateGameMismatch(path, found, expected)`; the message names both keys and the state path.
  - no sidecar, an unreadable sidecar, or a sidecar without `game_key` (a state written before this change): this is an UNLABELED state. Unlabeled states are accepted when `game.store_namespace is None` (the legacy game: every state that exists today is Red's) and refused for any namespaced game with `StateGameMismatch(path, None, game.key)` whose message says the state is unlabeled and may belong to another game. This keeps every existing Red state loading exactly as before.
- Both `PyBoyEmulator.load_state` and `FakeEmulator.load_state` call `check_state_game(path, self.game)` BEFORE touching the emulator, so a refused load changes nothing. `StateGameMismatch` is a `ValueError` subclass (callers that already catch `ValueError` on bad states keep working; `cli.py:83,127` get the new refusal as a normal error exit, and you add the one-line handling there if they would otherwise show a traceback: `error: <message>`, exit 2).

### Store call sites

Replace each literal in the fourteen listed modules with `store_path(...)`. Keep every module-level name that exists today (`MAPS_DEFAULT`, `MAPS_PATH`, `KB_PATH`, `DEFAULT_DIRS`, `_KB`); they are now assigned from `store_path`. Where the path is computed at import time and `POKEAGENT_GAME` would be read once at import, say so in a one-line comment; this is acceptable for a first step because a process runs one game. `kb/rom_tables.json` in `knowledge/kb.py` and `review/swarm.py`: namespace it the same way (`kb/<ns>/rom_tables.json` for a namespaced game). `explorer/context.py` must end at 299 lines or fewer: write the three defaults as `str(store_path("runs/maps.json"))`-style one-liners in place; if an import line would push it over, import `store_path` inside the existing import block by editing a line rather than adding one. `statemeta.tile_snapshot`'s default `maps_path` becomes a `None` default that resolves to `store_path("runs/maps.json")`, with the call result unchanged for Red.

## What NOT to do

- Do not touch `roms/`, `baselines/`, or any ROM data, and do not state where any game copy came from.
- Do not move, rename or rewrite any existing file under `runs/` or `kb/`: Red's data stays where it is. This phase changes where NEW paths resolve for a namespaced game; no migration script, no copy.
- Do not namespace `runs/agents`, `runs/explore-*`, `runs/swarm`, `runs/segments*`, `runs/legs` or `runs/anomalies*`; list them in the Report instead.
- Do not register a second game or add real-time input; `press()` is untouched.
- Do not change the schema of `maps.json`, `bandit.json`, `novelty.json` or checkpoint files, or add a game key inside them.
- Do not change `tools/` scripts or existing tests except as the Report lists (an existing test that asserts the exact bytes of a Red sidecar may need `game_key` added; edit minimally and list it).
- Every file stays under 300 lines; `explorer/context.py` and `explorer/memory.py` must not grow.
- No new dependency, no scratch or debug files outside `.devin-scratch/`.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_statemeta.py tests/test_cli.py tests/test_emulator.py tests/test_game_stores.py tests/test_game_state_guard.py tests/test_statemeta_game_key.py tests/test_store_callers.py tests/test_explorer_behaviours.py
```
Expected: all pass (the one `test_explorer_package_layering_and_size` case is the 300-line ceiling).

```
git grep -nE "\"runs/(maps|bandit|novelty)\.json\"|'runs/maps\.json'|Path\(\"runs/checkpoints\"\)|/ \"kb\" /" -- src
```
Expected: hits only in `src/pokeagent/game/stores.py` (doc/example strings) and docstrings; no executable use of those literals outside `game/stores.py`. List any remaining executable hit in the Report with the reason it was left.

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree.

## What the Claude verify lane must run afterwards, with the ROM

A Devin worktree has no ROM and no baselines (`roms/` and `baselines/` are gitignored), so every ROM-gated test skips there and a green Devin run proves nothing about real emulation. Claude runs in a fresh worktree of the PR head with `roms/` and `baselines/` junctioned in:

1. `uv run pytest -q tests/test_golden_red.py`. This is the gate: a changed hash means Red's store paths or state loading changed and the PR is rejected. It skips in a dispatch worktree because the ROM and baselines are absent; report it as NOT run, not as passed. Claude's ROM-present check runs it before merge. The recorded hash must not change (a deliberate change re-records it from a base-commit run in the same PR). The test reads `runs/explore-*` under its scratch dir, and Red stays on today's paths.
2. Load every existing checkpoint under `runs/checkpoints` and `runs/legs/states` through a Red emulator (`uv run pokeagent states list` or the `statescmd` check the repo already has, with the ROM): all must still load (they are unlabeled, accepted for Red), none may raise `StateGameMismatch`.
3. Write one new state with `write_state` under Red and confirm its sidecar has `"game_key": "pokemon-red"` and loads back.
4. Negative check with the ROM: hand-edit a COPY of a sidecar (in a temp dir, not under `runs/`) to `"game_key": "other"` and confirm the load is refused with the message naming both keys and the emulator state is unchanged.
5. `uv run pytest -q` with the ROM present: passed and skipped counts equal base, in particular `tests/test_statemeta.py`, `tests/test_segment_determinism.py`, `tests/test_seeding.py`.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Branch only (`directive/pokeagent-game-namespaced-stores-directive`); commit as you go; never commit to or push main; never merge.
- Tests are headless and need no ROM: `FakeEmulator`, synthetic fake `GameSpec` instances (a namespaced one with key `test-game`), `tmp_path` for every store and state file, `monkeypatch.chdir(tmp_path)` where a path is relative. Nothing may open a window, and no test may write into the real `runs/` or `kb/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and both grep outputs in the Report.

## Completion criteria

- [ ] `store_path` returns Red's paths unchanged for `runs/maps.json`, `runs/bandit.json`, `runs/novelty.json`, `runs/checkpoints`, `kb/items.json`, `kb/rom_tables.json`, with and without `root`; for a namespaced fake game it inserts the namespace as the second component; a path not under `runs` or `kb` raises `ValueError`; `POKEAGENT_GAME` is honoured when `game` is omitted. <!-- test: tests/test_game_stores.py --> <!-- new: tests/test_game_stores.py -->
- [ ] `GameSpec.store_namespace` validates (`None` or equal to `key`) and RED is `None`. <!-- test: tests/test_game_spec.py -->
- [ ] `check_state_game` passes a matching key, raises `StateGameMismatch` naming both keys for a different key, accepts unlabeled (no sidecar, no key, unreadable sidecar) for the legacy game, and refuses unlabeled for the namespaced fake game. <!-- test: tests/test_game_state_guard.py --> <!-- new: tests/test_game_state_guard.py -->
- [ ] `write_state` records `game_key`; `read_meta` still reads an old sidecar without the field (`game_key` is `None`); a Red `FakeEmulator` round-trips save then load; loading a state labeled for another game is refused BEFORE the emulator is touched (assert the fake's state is unchanged). <!-- test: tests/test_statemeta_game_key.py --> <!-- new: tests/test_statemeta_game_key.py -->
- [ ] Every call site in the scope list resolves to the identical string or `Path` for Red as before (assert per site: the `ExplorerContext` defaults, `cli_brain.MAPS_DEFAULT`, `mcp_server.MAPS_PATH`, `navigation.load_memory` default, `observations` default, `statescmd.DEFAULT_DIRS`, `hm_compat.KB_PATH`, `items_catalog.KB_PATH`, `knowledge.kb._KB`), and for the namespaced fake game under `monkeypatch.setenv("POKEAGENT_GAME", ...)` is not required (a process runs one game); the test calls `store_path` with the fake spec directly. <!-- test: tests/test_store_callers.py --> <!-- new: tests/test_store_callers.py -->
- [ ] The existing statemeta, CLI and emulator tests pass; any edit to an existing test is listed in the Report. <!-- test: tests/test_statemeta.py -->
- [ ] `explorer/context.py` and `explorer/memory.py` are at or below 299 lines. <!-- test: tests/test_explorer_behaviours.py -->
- [ ] The grep above is clean as stated, and `git diff --stat main` touches only the files in Scope plus tests and docs.
- [ ] Status row set to `Review` with the evidence above and the "Claude verify lane" section copied into the Status note.

## Report

Diff stat, test tails, the grep output, the new files' line counts, the list of executable `runs/` paths you found and deliberately left (with a one-line reason each), any existing test edited (file and lines), the exact refusal message text, and a plain statement that `tests/test_golden_red.py` (skipped), the existing-state load check and the ROM-present suite were NOT run (no ROM in the worktree) and are owed by the Claude verify lane.

## Forbidden Actions

- Do not touch `roms/`, `baselines/` or any ROM data, and do not state where a game copy came from.
- Do not move, copy, rewrite or delete anything under the real `runs/` or `kb/`.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not edit `tools/`, `world/`, `viewer/` or `src/pokeagent/mapview/`.
- Do not commit to or push main, merge, deploy, or open a window.

## Required from User

- None for the run. The ROM-present checks above are Claude's verify lane, not Robert's.
- Sequencing: do not approve this until `Game_Spec_Rom_Screen_Buttons_Directive.md` is merged. After it merges, the framework is safe for a second game to run (plan phase 4 stop point).

## Sandbox needs

- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
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
- 2026-11-08 12:16 · robert-claude-laptop · none → Queued — Drafted by Claude: plan phase 4; do not approve before Rom_Screen_Buttons merged
<!-- queue:end -->
