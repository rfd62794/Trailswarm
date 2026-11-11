# PokeAgent: namespace the shared stores by memory family, record the game in state sidecars, refuse a mismatched state load - Red and Blue share the legacy root, Red keeps today's paths (plan phase 4)

## Why this exists

Phase 4 of `docs/plans/Multi_Game_Framework_Plan.md` (branch `feat/watch-mario-land`, PR #169): "Namespace `runs/` and `kb/` by memory family, with Red on today's paths; game key in state sidecars; refuse a mismatched state load". The stop point is "safe for a second game to run". Rule that governs it: Pokemon Red behaviour stays byte-identical by default, Red's paths resolve to where they are today.

**Direction change, settled 2026-11-08 (owner):** "we want to try to build a combined or shared memory for red and blue, we want the individuality minimal where possible, and plan for yellow after confirming cross compatibility." So the unit of namespacing is a memory FAMILY, not a game. Red and Blue are one family and share the legacy root. A game that is not in that family (Yellow, until it passes the compat check; every non-Pokemon game) gets its own family and its own namespace. Per-game paths are kept only for what is bound to one ROM or measured to differ.

Measured 2026-11-08 by comparing Red's `runs/maps.json` (gitignored, so missing in a fresh worktree) with a Blue run's `maps.json` (15 maps, up to Viridian Forest; the Blue run had human interaction, so this is early evidence, not a verdict):

- 2,170 of 2,203 Blue tiles were already known to Red. 21 warps in common, none different. 35 of 35 stationary NPCs in the same place.
- 210 of 2,127 Red walls lie between two tiles Blue stood on (126 of them on Route 1, which has ledges). Likely one-way ledges or transient NPCs; the cause is UNCONFIRMED.
- A kb built from the Blue copy matched Red's except wild encounters (34 of 57 maps differ) and unexplained differences in `map_trainers` at unused ids 105-117 and 231.
- Blue's real RAM reads matched Red's map through the rival battle. Badges, wild battles and later maps are UNMEASURED.

So most stores are shared by default; wild encounter tables and anything bound to one ROM are per game.

**Depends on `Game_Spec_Rom_Screen_Buttons_Directive.md` being merged** (which depends on `Game_Spec_Package_Directive.md`). Start from a main where the earlier phase has added `src/pokeagent/game/paths.py` (missing on main until that phase merges) and `GameSpec.default_rom`. If `git grep -n "def default_rom" -- src` finds nothing at the start, stop and write that in the Status row.

Measured on main 2026-11-08 (every store below is shared with no game key; map ids are bare integers, so a second game would silently merge into Red's data):

- `runs/maps.json`: `src/pokeagent/explorer/context.py:33` (`maps_path`), `explorer/legacy.py:26`, `cli_brain.py:22` (`MAPS_DEFAULT`), `mcp_server.py:28` (`MAPS_PATH`), `navigation.py:17` (`load_memory`), `observations.py:33`, `statemeta.py:71` (`tile_snapshot`).
- `runs/bandit.json`: `explorer/context.py:37` (`bandit_path`); the store is `src/pokeagent/bandit/store.py`; `runs/` is gitignored, so these data files are missing in a fresh worktree.
- `runs/novelty.json`: `explorer/context.py:41` (`novelty_path`); the store is `src/pokeagent/novelty/store.py`; also missing in a fresh worktree.
- `runs/checkpoints`: `explorer/press_goals.py:62`, `explorer/press_track.py:53` and `:60`, `statescmd.py:16` (`DEFAULT_DIRS`).
- `kb/*`: `knowledge/hm_compat.py:14`, `knowledge/items_catalog.py:24`, `knowledge/kb.py:7` (`_KB` = `kb/rom_tables.json`), `statescmd.py:31`, `review/swarm.py:111`. The `kb/` data files are gitignored, so missing in a fresh worktree.
- `explorer/context.py` and `explorer/memory.py` are at 299 lines (ceiling 300, enforced by `tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size`): the edits there must not add a line.
- State sidecars: `src/pokeagent/statemeta.py` `StateMeta` (:20-33) has `game: dict` (a RAM snapshot: map_id, x, y, ...) but NO game key. `write_state` (:94) writes it; `read_meta` (:130) reads `StateMeta(**json)`; `load_state` (:125) loads then reads the meta. A Red state would load silently under any other game. `PyBoyEmulator.load_state` is `emulator.py:146`, `FakeEmulator.load_state` is `:200`; callers include `cli.py:83,127`, `cli_hex.py:43`, `mcp_server.py:154,217`, `invariants/states.py:74`, `adapters/explorer_snapshot.py:181`.
- `runs/agents/` (the agent registry), `runs/explore-*` (per-run directories), `runs/swarm`, `runs/segments*` and `runs/legs` are not in the plan's list; they are NOT moved by this directive (the Report lists what a grep finds so a later phase can decide).

Read first: `src/pokeagent/game/*.py`, `src/pokeagent/statemeta.py` (whole file, 150 lines), `src/pokeagent/emulator.py` lines 85-150 and 195-204, `src/pokeagent/bandit/store.py` and `src/pokeagent/novelty/store.py` (their path handling only), `tests/test_statemeta.py`.

## Store classification (settled; every store this directive lists)

Shared-by-default means the store is keyed by memory family. Per-game is kept only where a store is bound to one ROM or measured to differ. A later measurement can move a store from shared to per game; nothing moves the other way without a measurement.

| Store | Scope | Reason |
|---|---|---|
| `runs/maps.json` | family | measured: tiles, warps and stationary NPCs agree between Red and Blue. Disagreements are handled by the overlay in `Family_Shared_Memory_Directive.md`, not by a split here |
| `runs/bandit.json` | family | learned action statistics; nothing in it is tied to one ROM. UNVERIFIED for Blue (not measured) |
| `runs/novelty.json` | family | feature counts per run; same status as bandit. UNVERIFIED for Blue |
| `kb/hm_compat.json` | family | gitignored, missing in a fresh worktree; derived from the base-stats table; the Blue-built kb matched Red's |
| `kb/items.json` (items catalog) | family | gitignored, missing in a fresh worktree; same measurement |
| `kb/rom_tables.json` | family for the base, per game for the overlay | the Blue-built kb matched Red's except wild encounters (34 of 57 maps differ) and `map_trainers` at ids 105-117 and 231. This directive only routes the BASE file by family and exposes the per-game path; building the per-game overlay file is `Family_Shared_Memory_Directive.md` |
| `runs/checkpoints` | per game | a save state is bound to one ROM, even when memory is shared |
| `baselines/` | per game | a baseline trace is tied to one ROM. `baselines/` is outside `runs` and `kb`, so `store_path` does not route it and this directive does not move it. Red's stays where it is; a Blue baseline's location is decided by the clean-baseline step in the plan |

Not classified here, not moved: `runs/legs/states` and the other items in the "not moved" list above. States there are ROM-bound, so they must never be family-shared; the state guard still protects them.

## Scope (in this order)

1. `src/pokeagent/game/spec.py` and `src/pokeagent/game/pokemon_red.py` - two new fields, `memory_family` and `owns_legacy_paths`, and the constant `LEGACY_FAMILY`.
2. `src/pokeagent/game/stores.py` <!-- new: src/pokeagent/game/stores.py --> - `store_path(...)`, the single place that maps a store path to a path. Under 90 lines.
3. `src/pokeagent/game/state_guard.py` <!-- new: src/pokeagent/game/state_guard.py --> - `check_state_game(path, game)` and `StateGameMismatch`. Under 70 lines.
4. `src/pokeagent/statemeta.py` - `game_key` in `StateMeta`, written by `write_state`.
5. `src/pokeagent/emulator.py` - both `load_state` methods call the guard first.
6. The store call sites: `src/pokeagent/explorer/context.py`, `src/pokeagent/explorer/legacy.py`, `src/pokeagent/explorer/press_goals.py`, `src/pokeagent/explorer/press_track.py`, `src/pokeagent/cli_brain.py`, `src/pokeagent/mcp_server.py`, `src/pokeagent/navigation.py`, `src/pokeagent/observations.py`, `src/pokeagent/statemeta.py`, `src/pokeagent/statescmd.py`, `src/pokeagent/knowledge/hm_compat.py`, `src/pokeagent/knowledge/items_catalog.py`, `src/pokeagent/knowledge/kb.py`, `src/pokeagent/review/swarm.py`.
7. Tests, listed in the completion criteria.
8. `docs/KNOWLEDGE.md` - a paragraph on memory families, store scopes and the state guard.

## The work

### memory_family and owns_legacy_paths (spec.py, pokemon_red.py)

In `spec.py` add `LEGACY_FAMILY = "gen1-pokemon"` and two fields on `GameSpec` (no defaults):

- `memory_family: str` - the family whose memory this game shares; every game declares it. The family is `gen1-pokemon` (the model is assumed compatible only with Generation 1 Pokemon: Red and Blue now, Yellow only if it passes the compat check); games such as Mario or Kirby are simply not in it. Same slug rule as `key`. `LEGACY_FAMILY` means "the legacy root": the family's family-scope stores live exactly where they do today.
- `owns_legacy_paths: bool` - True for exactly one game, Red: its per-game stores also stay on today's paths. Validation: `owns_legacy_paths` requires `memory_family == LEGACY_FAMILY`.

RED sets `memory_family=LEGACY_FAMILY, owns_legacy_paths=True`. Only RED exists after this phase and no second game is registered here. The Blue phase registers Blue with `memory_family=LEGACY_FAMILY, owns_legacy_paths=False`, which is how Blue joins Red's family; this directive builds and tests that case with a fake spec, it does not register Blue. Any game outside the family sets `memory_family` to its own key (for example `"test-game"`). A registry-level test asserts that at most one registered game has `owns_legacy_paths` and that no non-legacy `memory_family` equals a different game's `key`.

### stores.py

`store_path(rel: str | Path, game: GameSpec | None = None, root: Path | None = None, scope: str = "family") -> Path`:

- `rel` must start with `runs` or `kb` (a `ValueError` otherwise: the only two namespaced roots). `scope` is `"family"` or `"game"` (a `ValueError` otherwise).
- `scope="family"`: if `game.memory_family == LEGACY_FAMILY` return `rel` unchanged (`Path(rel)`, or `root / rel` when `root` is given). Byte-identical for Red and for Blue. Otherwise insert `memory_family` as the second path component: `runs/maps.json` -> `runs/<family>/maps.json`, `kb/items.json` -> `kb/<family>/items.json`.
- `scope="game"`: if `game.owns_legacy_paths` return `rel` unchanged. Otherwise insert `game.key` as the second component: `runs/checkpoints` -> `runs/pokemon-blue/checkpoints`, and for a game in its own family `runs/test-game/checkpoints`. A game's family-scope and game-scope paths may share a directory; they never name the same file.
- Never create directories (callers already `mkdir(parents=True)` where they write).
- `game=None` resolves through `resolve_game(None)` so `POKEAGENT_GAME` is honoured.
- `rel` may be given as `str` or `Path`, with `/` or `\`; return a `Path`. Where a call site stores the path as a `str` field (`explorer/context.py` fields `maps_path`, `bandit_path`, `novelty_path`; `cli_brain.MAPS_DEFAULT`), keep the field a `str` equal to `store_path(...).as_posix()` so the value for Red is the identical string `"runs/maps.json"`.

### state_guard.py and statemeta.py

A save state is ROM-bound even when memory is shared, so the sidecar keeps the GAME key (not the family) and a mismatched load is still refused. A Red state never loads under Blue, and the reverse.

- `StateMeta` gains `game_key: str | None = None` (last field, so older sidecars without it still load through `StateMeta(**data)`). `write_state` sets it from the emulator's game: `getattr(getattr(emu, "game", None), "key", None)`, falling back to `"pokemon-red"` ONLY when the emulator has no `game` attribute at all (the phase 3 emulators always have one; the fallback is for test doubles). Sidecars written for Red now carry `"game_key": "pokemon-red"`; that is the only change to Red's written bytes and the golden trace is not affected (it compares transitions, not sidecars).
- `check_state_game(path: Path, game: GameSpec) -> None`: reads `statemeta.sidecar(path)` if it exists (use `json.loads` directly; do not import `statemeta` here if that creates a cycle: read the one key). Rules:
  - sidecar has `game_key` equal to `game.key`: pass.
  - sidecar has a `game_key` that differs: raise `StateGameMismatch(path, found, expected)`; the message names both keys and the state path. This applies between Red and Blue even though they share memory.
  - no sidecar, an unreadable sidecar, or a sidecar without `game_key` (a state written before this change): this is an UNLABELED state. Unlabeled states are accepted when `game.owns_legacy_paths` (every state that exists today is Red's) and refused for every other game, family member or not, with `StateGameMismatch(path, None, game.key)` whose message says the state is unlabeled and may belong to another game. This keeps every existing Red state loading exactly as before.
- Both `PyBoyEmulator.load_state` and `FakeEmulator.load_state` call `check_state_game(path, self.game)` BEFORE touching the emulator, so a refused load changes nothing. `StateGameMismatch` is a `ValueError` subclass (callers that already catch `ValueError` on bad states keep working; `cli.py:83,127` get the new refusal as a normal error exit, and you add the one-line handling there if they would otherwise show a traceback: `error: <message>`, exit 2).

### Store call sites

Replace each literal in the fourteen listed modules with `store_path(...)`, using the scope from the classification table: `scope="game"` for the checkpoint sites (`explorer/press_goals.py:62`, `explorer/press_track.py:53` and `:60`, `statescmd.py:16` `DEFAULT_DIRS`), the default `scope="family"` for every other site. Keep every module-level name that exists today (`MAPS_DEFAULT`, `MAPS_PATH`, `KB_PATH`, `DEFAULT_DIRS`, `_KB`); they are now assigned from `store_path`. Where the path is computed at import time and `POKEAGENT_GAME` would be read once at import, say so in a one-line comment; this is acceptable for a first step because a process runs one game. `kb/rom_tables.json` in `knowledge/kb.py` and `review/swarm.py`: family scope (the shared base; the per-game overlay is read by the family-memory directive, not here). `explorer/context.py` must end at 299 lines or fewer: write the three defaults as `str(store_path("runs/maps.json"))`-style one-liners in place; if an import line would push it over, import `store_path` inside the existing import block by editing a line rather than adding one. `statemeta.tile_snapshot`'s default `maps_path` becomes a `None` default that resolves to `store_path("runs/maps.json")`, with the call result unchanged for Red.

## What NOT to do

- Do not touch `roms/`, `baselines/`, or any ROM data, and do not state where any game copy came from.
- Existing tests that build a `GameSpec(...)` directly (for example `tests/test_game_spec.py` and `tests/test_emulator_game.py`) break when `memory_family` and `owns_legacy_paths` are added without defaults. You may make the minimal edit to each such test: pass the two new arguments (or use `dataclasses.replace(RED, ...)`), and change no assertion. List every such test and its lines in the Report. This is the only permitted edit to existing tests apart from the sidecar-bytes case named below.
- Do not move, rename or rewrite any existing file under `runs/` or `kb/`: Red's data stays where it is. This phase changes where NEW paths resolve for a game outside the legacy family or for a game-scope store; no migration script, no copy.
- Do not namespace `runs/agents`, `runs/explore-*`, `runs/swarm`, `runs/segments*`, `runs/legs` or `runs/anomalies*`; list them in the Report instead.
- Do not register Blue or any second game, and do not add real-time input; `press()` is untouched.
- Do not build overlays, provenance, a merge, or any read-through of a second file. That is `Family_Shared_Memory_Directive.md`; this directive only routes paths.
- Do not change the schema of `maps.json`, `bandit.json`, `novelty.json` or checkpoint files, or add a game key inside them.
- Do not change `tools/` scripts or existing tests except as permitted above and as the Report lists (an existing test that asserts the exact bytes of a Red sidecar may need `game_key` added; edit minimally and list it).
- Every file stays under 300 lines; `explorer/context.py` and `explorer/memory.py` must not grow.
- No new dependency, no scratch or debug files outside `.devin-scratch/`.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_statemeta.py tests/test_cli.py tests/test_emulator.py tests/test_game_stores.py tests/test_game_state_guard.py tests/test_statemeta_game_key.py tests/test_store_callers.py tests/test_explorer_behaviours.py
```
Expected: all pass (the one `test_explorer_package_layering_and_size` case is the 300-line ceiling).

```
git grep -n -F -e '"runs/maps.json"' -e '"runs/bandit.json"' -e '"runs/novelty.json"' -e 'Path("runs/checkpoints")' -e '/ "kb" /' -- src
```
Expected: hits only in `src/pokeagent/game/stores.py` (doc/example strings) and docstrings; no executable use of those literals outside that file. List any remaining executable hit in the Report with the reason it was left.

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree.

## What the Claude verify lane must run afterwards, with the ROM

A Devin worktree has no ROM and no baselines (`roms/` and `baselines/` are gitignored), so every ROM-gated test skips there and a green Devin run proves nothing about real emulation. Claude runs in a fresh worktree of the PR head with `roms/` and `baselines/` junctioned in:

1. `uv run pytest -q tests/test_golden_red.py`. This is the gate: a changed hash means Red's store paths or state loading changed and the PR is rejected. It skips in a dispatch worktree because the ROM and baselines are absent; report it as NOT run, not as passed. Claude's ROM-present check runs it before merge. The recorded hash must not change (a deliberate change re-records it from a base-commit run in the same PR). The test reads `runs/explore-*` under its scratch dir, and Red stays on today's paths.
2. Load every existing checkpoint under `runs/checkpoints` and `runs/legs/states` through a Red emulator (`uv run pokeagent states list` or the `statescmd` check the repo already has, with the ROM): all must still load (they are unlabeled, accepted for Red), none may raise `StateGameMismatch`.
3. Write one new state with `write_state` under Red and confirm its sidecar has `"game_key": "pokemon-red"` and loads back.
4. Negative check with the ROM: hand-edit a COPY of a sidecar (in a temp dir, not under `runs/`) to `"game_key": "other"` and confirm the load is refused with the message naming both keys and the emulator state is unchanged. (The Red-versus-Blue refusal itself needs a Blue ROM and is checked in the Blue phase.)
5. `uv run pytest -q` with the ROM present: passed and skipped counts equal base, in particular `tests/test_statemeta.py`, `tests/test_segment_determinism.py`, `tests/test_seeding.py`.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Branch only (`directive/pokeagent-game-namespaced-stores-directive`); commit as you go; never commit to or push main; never merge.
- Tests are headless and need no ROM: `FakeEmulator`, synthetic fake `GameSpec` instances, `tmp_path` for every store and state file, `monkeypatch.chdir(tmp_path)` where a path is relative. Nothing may open a window, and no test may write into the real `runs/` or `kb/`. The fakes are `test-game` (its own family, `owns_legacy_paths=False`) and `test-sibling` (`memory_family=LEGACY_FAMILY`, `owns_legacy_paths=False`, standing in for Blue).
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and both grep outputs in the Report.

## Completion criteria

- [ ] `store_path` with scope `family` returns Red's paths unchanged for `runs/maps.json`, `runs/bandit.json`, `runs/novelty.json`, `kb/items.json`, `kb/rom_tables.json`, with and without `root`; with scope `game` it returns `runs/checkpoints` unchanged for Red. For the sibling fake (`test-sibling`) the family-scope paths are identical to Red's and the game-scope path is `runs/test-sibling/checkpoints`. For the own-family fake (`test-game`) family scope inserts the family as the second component and game scope inserts the key. A path not under `runs` or `kb`, and an unknown scope, raise `ValueError`; `POKEAGENT_GAME` is honoured when `game` is omitted. <!-- test: tests/test_game_stores.py --> <!-- new: tests/test_game_stores.py -->
- [ ] `GameSpec` validates `memory_family` and `owns_legacy_paths` (the latter requires the legacy family), RED has `LEGACY_FAMILY` and `True`, and the registry holds at most one game with `owns_legacy_paths`. <!-- test: tests/test_game_spec.py -->
- [ ] `check_state_game` passes a matching key, raises `StateGameMismatch` naming both keys for a different key (including a sibling-family game loading the other's state), accepts unlabeled (no sidecar, no key, unreadable sidecar) for Red, and refuses unlabeled for both fakes. <!-- test: tests/test_game_state_guard.py --> <!-- new: tests/test_game_state_guard.py -->
- [ ] `write_state` records `game_key`; `read_meta` still reads an old sidecar without the field (`game_key` is `None`); a Red `FakeEmulator` round-trips save then load; loading a state labeled for another game is refused BEFORE the emulator is touched (assert the fake's state is unchanged). <!-- test: tests/test_statemeta_game_key.py --> <!-- new: tests/test_statemeta_game_key.py -->
- [ ] Every call site in the scope list resolves to the identical string or `Path` for Red as before (assert per site: the `ExplorerContext` defaults, `cli_brain.MAPS_DEFAULT`, `mcp_server.MAPS_PATH`, `navigation.load_memory` default, `observations` default, `statescmd.DEFAULT_DIRS`, `hm_compat.KB_PATH`, `items_catalog.KB_PATH`, `knowledge.kb._KB`), and each site's scope matches the classification table (checkpoint sites game scope, the rest family scope); namespaced behaviour is tested by calling `store_path` with the fakes directly, not through `POKEAGENT_GAME` (a process runs one game). <!-- test: tests/test_store_callers.py --> <!-- new: tests/test_store_callers.py -->
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
- Sequencing: do not approve this until `Game_Spec_Rom_Screen_Buttons_Directive.md` is merged. After it merges, the framework is safe for a second game to run (plan phase 4 stop point). `Game_Compat_Check_Directive.md` and `Family_Shared_Memory_Directive.md` follow it.

## Sandbox needs

- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git grep)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-game-namespaced-stores-directive |
| Base branch | - |
| Base commit | 8d84c6f226366c5fc4d1055583c615f2ec2d613b |
| Head commit | 420a4d90af6c8e2070bb0ead8dfa1a06f0cae907 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-08 12:16 · robert-claude-laptop · none → Queued — Drafted by Claude: plan phase 4; do not approve before Rom_Screen_Buttons merged
- 2026-11-10 18:56 · robert-claude-laptop · Queued → Approved
- 2026-11-10 19:03 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-game-namespaced-stores-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M73YMQGYQ2Q9SVATSB0M9K1J
- 2026-11-10 19:07 · dispatcher · launched pid=21816; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-game-namespaced-stores-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (4 declared need(s), repo-scoped only))
- 2026-11-10 19:21 · devin · In progress → Review — Done on directive/pokeagent-game-namespaced-stores-directive, commit 420a4d9 (pushed). DIFF STAT vs main: 29 files, +584/-25 — spec.py +pokemon_red.py (LEGACY_FAMILY="gen1-pokemon", memory_family, owns_legacy_paths + validation), new game/stores.py (46 lines) + game/state_guard.py (53 lines), statemeta.py (game_key last field, write_state sets it, tile_snapshot None->store_path), emulator.py (guard in both load_state), cli.py (_cmd_run: StateGameMismatch -> 'error: msg', exit 2), all 14 call sites routed via store_path, goals.py re-exports store_path for the explorer package (layering test bars pokeagent.game imports — same pattern as the existing is_unverified re-export), KNOWLEDGE.md paragraph, 4 new test files, 3 minimal test edits. TEST TAILS: - targeted (directive list): 107 passed in 3.29s - spec/paths/cli flag/emulator subset: 62 passed - full suite `uv run pytest -q`: 2384 passed, 41 skipped in 163s — no new failures; ROM-gated tests skipped (no ROM in worktree). GREP (`git grep -n -F -e '"runs/maps.json"' -e '"runs/bandit.json"' -e '"runs/novelty.json"' -e 'Path("runs/checkpoints")' -e '/ "kb" /' -- src`): 9 hits, ALL of them the literal rel argument inside a store_path(...) call (cli_brain:23, context:33/37/41, legacy:27, mcp_server:29, navigation:19, observations:35, statemeta:74) — those are the router's argument by design, not hard-coded paths. Zero bare Path("runs/checkpoints") and zero `/ "kb" /` joins remain (the '/ "kb" /' pattern returns nothing even pre-change — a git-grep quirk on patterns starting with '/'; the six real kb sites were verified fixed via `git grep '"kb"'`). NEW FILE LINES: game/stores.py 46, game/state_guard.py 53, tests/test_game_stores.py 89, tests/test_game_state_guard.py 97, tests/test_statemeta_game_key.py 79, tests/test_store_callers.py 106. context.py and memory.py both at 299 lines (<=299 as required; context.py lost one blank line, no content removed). EXECUTABLE runs/ PATHS DELIBERATELY LEFT (not in the classification table / explicitly not moved): press_goals.py:72 runs/milestones.json (unclassified); statescmd.py:20 Path("runs/legs/states") + legs/states.py:16 (ROM-bound states, never family-shared); legs/drill.py:22 + grind/* (runs/legs/*, runs/grind_points.json, runs/grind_atlas.json); mcp_server.py:28 runs/mcp (per-run dir); statelog.py:21 runs/retired; explorer/behaviours/battle.py:276 runs/battles.jsonl; explorer/demos.py:28 + intervene/ops.py:15 (runs/interventions.jsonl / agent_interventions.jsonl); explorer/economy/plan.py:28 runs/economy.json; adapters/explorer_snapshot.py runs/states; atlas/overrides.py + world/export.py runs/atlas/*; procedures/store.py:19 runs/procedures; runlog.py:30 runs/ root. Docstring/help-text mentions of runs/agents, runs/explore-*, runs/swarm, runs/segments*, runs/anomalies* remain as text only — listed for a later phase, not moved. EXISTING TESTS EDITED (minimal, per the directive's allowance): tests/test_game_spec.py _KW dict +2 fields (memory_family="x-game", owns_legacy_paths=False) and 5 NEW test functions appended (spec validation + registry-level asserts) — no existing assertion changed; tests/test_emulator_game.py TINY +2 fields; tests/test_game_frame_size.py TINY +2 fields. No sidecar-bytes assertion needed editing. REFUSAL MESSAGE TEXT (StateGameMismatch, a ValueError): labeled mismatch -> "state {path} was written for {found}, refusing to load it under {expected}"; unlabeled -> "state {path} is unlabeled (no game_key in its sidecar): it may belong to another game, refusing to load it under {expected}". DESIGN NOTE: the explorer package's layering test (tests/test_explorer_behaviours.py, allowed-import set) forbids importing pokeagent.game even inside functions, so context.py/legacy.py/press_goals.py/press_track.py import store_path via the pokeagent.goals re-export — the existing 'is_unverified = campaign.is_unverified' precedent. All non-explorer sites import game.stores directly. kb/rom_tables.json routed at family scope (shared base) as instructed. NOT RUN (no ROM / baselines in this worktree — owed by the Claude verify lane): tests/test_golden_red.py (skipped here, recorded hash gate), the load-every-existing-checkpoint check under runs/checkpoints and runs/legs/states, the ROM-present full suite, the write-new-Red-state sidecar check, and the hand-edited-sidecar negative check. CLAUDE VERIFY LANE (copied from the directive): 1. `uv run pytest -q tests/test_golden_red.py` — the gate: a changed hash means Red's store paths or state loading changed and the PR is rejected. It skips in a dispatch worktree because the ROM and baselines are absent; report it as NOT run, not as passed. Claude's ROM-present check runs it before merge. The recorded hash must not change. 2. Load every existing checkpoint under runs/checkpoints and runs/legs/states through a Red emulator (uv run pokeagent states list or the statescmd check, with the ROM): all must still load (unlabeled, accepted for Red), none may raise StateGameMismatch. 3. Write one new state with write_state under Red and confirm its sidecar has "game_key": "pokemon-red" and loads back. 4. Negative check with the ROM: hand-edit a COPY of a sidecar (temp dir, not under runs/) to "game_key": "other" and confirm the load is refused with the message naming both keys and the emulator state is unchanged. 5. `uv run pytest -q` with the ROM present: passed and skipped counts equal base, in particular tests/test_statemeta.py, tests/test_segment_determinism.py, tests/test_seeding.py. [origin] spent: devin 13 min est. n/a
- 2026-11-10 21:00 · robert-claude-laptop · Review → Done — note: Trailswarm #187 merged c255a574f, pinned 420a4d90a; independent Sonnet review APPROVE; verify 2384 passed / 0 failed / 41 skipped (the ROM-gated baseline per Robert's rule)
<!-- queue:end -->
