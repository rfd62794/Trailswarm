# PokeAgent: Build comparison and Library tab - compare team builds per checkpoint and leg in a CLI report and a native Library tab, with a "load into World view" action

**Depends on `Save_Library_And_Party_Gate_Directive.md` and `Curriculum_Build_Selection_Directive.md` merged.** The first adds the library index `runs/states/library.json` (`src/pokeagent/statelib/library.py`) and `src/pokeagent/team_fp.py`; the second adds the `build` and `cell` keys on segment attempts and `runs/states/build_tries.json` (`src/pokeagent/statelib/cells.py`). If `git grep -n "def to_archive" -- src/pokeagent/statelib/cells.py` finds nothing at the start of the run, stop and write that in the Status row; do not recreate those modules. Base: a main that contains both.

## Why this exists

Robert, 2026-11-14, on the save library: the checkpoints and legs, each with alternative team builds, should be comparable at a glance, and a state should be openable in the World view. Today there is no way to see which build gets to the next checkpoint fastest, loses fewest members, or wins the boss. The data will exist once the two earlier directives merge: library entries carry `build`, `verdict` and `metrics`; each segment attempt in `runs/segments.json` carries `build` and `cell` (`tools/seg_ingest.py` `build_attempt`); battles are in `runs/battles.jsonl`.

The viewer is a Dear PyGui desktop app. Robert's rule (2026-11-12, "Trailswarm desktop UI only"): no web or phone views. This directive adds a CLI report and a native tab, nothing else.

## Scope (in this order)

1. `src/pokeagent/statelib/compare.py` <!-- new: src/pokeagent/statelib/compare.py --> - pure: build the comparison rows from the library index, the segments doc and battle records. Under 150 lines.
2. `src/pokeagent/statelib/compare_report.py` <!-- new: src/pokeagent/statelib/compare_report.py --> - text and JSON rendering of the rows. Under 90 lines.
3. `src/pokeagent/statescmd.py` - `pokeagent states library compare [--segment S] [--json]` (a subcommand beside `build|list|validate`).
4. `src/pokeagent/viewer/ui/library_model.py` <!-- new: src/pokeagent/viewer/ui/library_model.py --> - pure view-model (no dearpygui import): the tree rows and the sort/expand state. Under 120 lines.
5. `src/pokeagent/viewer/ui/library_view.py` <!-- new: src/pokeagent/viewer/ui/library_view.py --> - the Dear PyGui tab, built only from the view-model. Under 150 lines.
6. Wiring: `src/pokeagent/viewer/modes.py` (view vocabulary), `src/pokeagent/viewer/ui/window.py` (host and view switch), `src/pokeagent/viewer/ui/menu.py` (View menu entry), the one place `world_host.py` / `world_view.py` gets a "go to map and tile" call (see below).
7. Tests: `tests/test_statelib_compare.py`, `tests/test_states_library_compare_cli.py`, `tests/test_library_model.py`, `tests/test_library_view_headless.py` <!-- new: tests/test_statelib_compare.py --> <!-- new: tests/test_states_library_compare_cli.py --> <!-- new: tests/test_library_model.py --> <!-- new: tests/test_library_view_headless.py -->.
8. `docs/KNOWLEDGE.md` - two lines under the "Save library" paragraph: the report command and the tab.

## The work

Existing facts, pasted (the worktree cannot be searched). `uv run python --version` prints `Python 3.12.12`.

```
# library entry (first directive): {"tier": "checkpoint"|"leg", "name", "segment", "state", "build", "team", "verdict", "violations",
#   "run", "seed", "parent", "created", "metrics": {"steps", "faints", "readiness", "readiness_boss"}}
# tools/seg_store.py: load(root) -> doc {"stats": {segment_key: {"attempts": [...], "n", "solves", "best", "confirmed"}}, "splits": {...}}
#   an attempt (tools/seg_ingest.py build_attempt): {"run", "solved", "frames", "steps", "seed", "starter", "maps", "tagged", "est",
#   "blackouts", "stalled", "provenance", "build" (new), "cell" (new), ...}
# runs/battles.jsonl: one JSON object per battle, keys include run, stage, trainer (null for wild), outcome ("won"|...), won, turns, party_before, party_after, hp_end
#   party_*: [[species, level, exp, hp, max_hp], ...]; a member fainted in the fight when its hp is > 0 before and 0 after
# src/pokeagent/explorer/economy/budget.py: BOSS_GOALS = ("beat_brock", "beat_misty", "beat_surge", "beat_erika", "beat_koga", "beat_sabrina", "beat_blaine", "beat_giovanni")
# src/pokeagent/viewer/modes.py: DEFAULT_MODE = "world"; CHOICES = ("tiles", "world"); _TO_INTERNAL = {"tiles": "grid", "world": "world"}; _LABEL = {"grid": "Tiles", "world": "World", "focus": "Focus"}
# src/pokeagent/viewer/ui/window.py: ViewerWindow.set_view_mode(mode) switches 'grid' | 'world' (FocusState.MODES); self.world = WorldHost(self, world);
#   (self.stitched or self.world).follow(agent_id) / .build() / .fit(vw, avail) / .tick(); WorldHost.tick() shows/hides its area by self.win.focus.view == "world"
# src/pokeagent/viewer/ui/world_side.py: WorldSide.show_tile(map_id, x, y) fills the side panel with describe(map_id, x, y, ...)
# src/pokeagent/viewer/dpg_stub.py: StubDpg (a counting stand-in for dearpygui, no window); the existing headless viewer tests use it or build with `win.stitched.build(headless=True)`
# src/pokeagent/vision_model/view_window.py: the standalone-window pattern: `run(panels, title)` imports dearpygui inside the function, builds textures, never called by tests
```

### 1. Comparison rows (compare.py), pure

`compare_rows(entries, segments_doc, battles, *, segment=None) -> list[Row]` where `Row` is a frozen dataclass:
`segment: str | None, tier: str, name: str, build: str | None, verdict: str, n_states: int, attempts: int, solves: int, solve_rate: float | None, median_steps: int | None, median_frames: int | None, faints_per_attempt: float | None, boss_win_rate: float | None, boss_battles: int, readiness: float | None, tries: int`. One row per `(segment, tier, name-or-segment key, build)`.
- Attempts of a build: the attempts in `segments_doc["stats"][segment]["attempts"]` whose `build` equals the row's build (attempts without `build` count under the build `None`, shown as `-`). `solve_rate` = solves / attempts (None for 0 attempts); medians over solved, non-estimated (`est` false) attempts only (None when none).
- `faints_per_attempt`: for each attempt's `run` sum the members that fainted in that run's battles in `battles` (hp above 0 before, 0 after, matched by slot; skip battles whose party lengths differ), divided by attempts with battle data; None when there are no battle records for any attempt of the row. Never estimate.
- `boss_win_rate`: among that build's attempts' runs, battles with `trainer` not null and `stage` equal to the segment goal when that goal is in `BOSS_GOALS`; won / total, with `boss_battles` the total; None when the goal is not a boss goal or there are none.
- `readiness` is the library entry's `metrics.readiness` (best entry of the row); `tries` from `build_tries.json` when passed (`tries: dict`).
- Sort: segment in chain order (`GOALS` index), then build with the best `solve_rate` first. `segment=` filters one segment.

### 2. CLI report (compare_report.py + statescmd.py)

`pokeagent states library compare [--segment S] [--json]`: loads `runs/states/library.json` (exit 1 with `no library: run 'pokeagent states library build'` when absent), the segments doc through `seg_store.load`, and `runs/battles.jsonl` tolerantly (a missing or bad line counts as no data). Prints a fixed-width table (segment, tier, name, build, verdict, n, attempts, solve%, median steps, faints/attempt, boss win%, readiness, tries), `-` for None; `--json` prints the rows as a JSON list. No emulator, no window.

### 3. Library tab (viewer)

Pick the host by reading the code: the main viewer (`src/pokeagent/viewer/ui/window.py` `ViewerWindow`, views Tiles | World) is the right host, not the vision viewer (`src/pokeagent/vision_model/view_window.py` is the standalone-window PATTERN to copy: dearpygui imported inside the function that opens a window, pure builders elsewhere). Add a third view `library`:
- `modes.py`: add `"library"` to `CHOICES`, `_TO_INTERNAL`, `_LABEL` (`"Library"`), keeping `DEFAULT_MODE = "world"`. `FocusState.MODES` (`src/pokeagent/viewer/layout.py` line 33, currently `("grid", "world")`) must accept `"library"`; `FocusState.set_mode` (line ~45) only switches while nothing is focused, and `ViewerWindow.set_view_mode` already leaves focus first. Check that nothing else assumes exactly two modes (`toggle_view_mode` flips grid/world: leave it as it is, the Library view is reached from the menu).
- `library_model.py` (pure, no dpg): `LibraryModel(entries, rows)` with `tree() -> list[Node]`: top-level nodes are checkpoints in chain order (`GOALS` index), each expandable to the leg states of its segment; under each node one line per build with the comparison columns above (solve rate, median steps, faints/attempt, boss win rate, verdict); `toggle(node_id)` expands/collapses; `sort_by(column)`; `flagged()` lists `violation` entries (shown in red text with the violation reason). Deterministic given its inputs.
- `library_view.py` (`LibraryView`): builds a DPG child area with `dpg.table` or tree nodes from `LibraryModel.tree()`; columns as above; a button column "Load into World view" on every row that has a state path; a "Rebuild" button that reruns `statelib.library` build (no emulator) and refreshes. It reads the library file on build and on Rebuild only, never per frame.
- "Load into World view": `ViewerWindow.load_state_in_world(path)`: read the state's fingerprint (`statefp.read(path)`: `map`, `x`, `y`; no emulator is started), `set_view_mode("world")`, then centre the World camera on `(map, x, y)` and call `WorldSide.show_tile(map, x, y)`. `src/pokeagent/viewer/ui/world_view.py` `WorldView` has `follow_agent(agent_id)`, `fit(w, h)` and `update(now)` but no goto-a-tile method (Claude listed its methods); add one small method `WorldView.goto(map_id, x, y)` that centres the camera on the tile (read how `follow_agent` and `_frame` position the camera and reuse that), and call it. A state with no fingerprint map shows a one-line status message instead and changes nothing. This action never loads the ROM, never starts an agent and never sends input.
- Menu: `src/pokeagent/viewer/ui/menu.py` View menu gets "Library" next to the existing items; the status line (`modes.status_text`) keeps working for the new view (`label("library")` is "Library").
- Window wiring: `ViewerWindow` creates the `LibraryView` lazily on first switch to the library view (so a viewer that never opens it pays nothing) and shows/hides its area in the per-frame tick the same way `WorldHost.tick` does.

### Tests (`tests/test_statelib_compare.py`, `tests/test_states_library_compare_cli.py`, `tests/test_library_model.py`, `tests/test_library_view_headless.py`)

All synthetic (`tmp_path` library, hand-built attempts and battle records). Never open a window: the view test either uses `StubDpg` (see `src/pokeagent/viewer/dpg_stub.py` and how `tests/test_viewer_world_stitched.py` builds headless) or only tests `LibraryModel` and the `load_state_in_world` call path with a stub window object. If `dearpygui` is not importable in the worktree, the dpg-touching test uses `pytest.importorskip("dearpygui.dearpygui")` inside the test.

## What NOT to do

- No web view, no HTML, no browser, no server; no phone view. Desktop Dear PyGui only.
- Do not open a window or send input in any test, and do not start an emulator or agent from the tab or the CLI. Do not change `WorldModel` data, `world/export.py` or the stitched view's behaviour.
- Do not edit the library index schema or the curriculum modules (those are the earlier directives); only read them.
- Do not read `runs/`, `roms/` or `baselines/` in tests.
- No new dependency. Keep the new viewer files under their line limits; `window.py` gets a few lines of wiring, not logic.
- Do not state where any game copy came from.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_statelib_compare.py tests/test_states_library_compare_cli.py tests/test_library_model.py tests/test_library_view_headless.py
```
Expected: all pass (the dpg test may skip without dearpygui; say so).

```
uv run --frozen pytest -q tests/test_viewer_world_stitched.py tests/test_viewer_agents.py tests/test_viewer_tiles_world.py tests/test_statelog.py
```
Expected: no new failures (existing viewer and ledger tests, unchanged). Claude ran this exact command on main while writing the directive; the tail is in the PR description.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: the files in Scope only.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-build-comparison-and-library-tab-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `compare_rows` computes solve rate, medians over solved non-estimated attempts, faints per attempt and boss win rate from synthetic inputs, returns None where data is missing, and sorts in chain order. <!-- test: tests/test_statelib_compare.py -->
- [ ] `pokeagent states library compare` prints the table and `--json` output, filters by `--segment`, and exits 1 with the `no library` message when the index is absent. <!-- test: tests/test_states_library_compare_cli.py -->
- [ ] `LibraryModel.tree()` orders checkpoints in chain order, expands to legs, lists builds per node with the comparison columns, flags violation entries, and `sort_by` / `toggle` behave. <!-- test: tests/test_library_model.py -->
- [ ] The view modes accept `library`, `label("library")` is `Library`, the default mode is still `world`, and the existing mode tests pass. <!-- test: tests/test_library_view_headless.py -->
- [ ] `load_state_in_world` reads only the sidecar, switches to the world view and calls the tile/camera method with the fingerprint's map, x, y; a state without a fingerprint changes nothing. <!-- test: tests/test_library_view_headless.py -->
- [ ] The four existing test files above pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails (which tests skipped for lack of dearpygui, if any), the new files' line counts, and which existing World-view method the load action uses (the new `WorldView.goto`). Then the checks Claude runs afterwards on the laptop (Devin cannot):

1. After the first two directives' ROM steps have produced a real `runs/states/library.json`: `uv run pokeagent states library compare` and read it against `runs/segments.json`.
2. Open the viewer on the laptop (Claude, never on Robert's screen while he is using it, and without sending any input): `uv run pokeagent view`, switch to the Library view from the View menu, expand a checkpoint, press "Load into World view" on a clean and on a flagged entry, and confirm the World view centres on the right map with no emulator started.
3. Confirm no new files appear under `runs/` other than `runs/states/library.json` from the Rebuild button.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input, in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The first two directives merged before dispatch, and the laptop checks in the Report section, run by Claude. Nothing else blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
