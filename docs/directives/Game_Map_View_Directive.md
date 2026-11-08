# PokeAgent: game-agnostic Map view - every area stitched and browsable, every agent replayed across them at once as ghosts, from generic files only

## Why this exists

Robert, 2026-11-08, top priority: he wants to see the full stitched map of every level or area and every agent across those maps at once, the way the Pokemon world view shows Kanto. Today the Mario tools write exactly the data for that and nothing draws it: `tools/mario_maps.py` (PR #169, branch `feat/watch-mario-land`, in review) writes stitched area images and ghost tracks, and `tools/watch_game.py` shows only one gameplay screen. This is plan step V3 of `docs/plans/Multi_Game_Framework_Plan.md` ("Map tab in the viewer"), built ahead of plan phases 2 to 4 on purpose: it depends on the ghost and map file formats only, not on `GameSpec`, so it can ship while the game package is still being built.

**Base requirement:** `tools/mario_maps.py`, `tools/watch_game.py` and `docs/plans/Multi_Game_Framework_Plan.md` live on PR #169 and are not on main yet. Start this run from a main that contains PR #169. If `git grep -n "ghosts" -- tools/mario_maps.py` finds nothing at the start of the run, stop and write that in the Status row; do not recreate those files. This directive does not need those files to exist to pass its tests (they use synthetic fixtures); they are the format reference only.

The two file formats, pasted because the worktree cannot be searched and the files may be absent:

Area index, `<source>/maps/index.json`, written atomically by `tools/mario_maps.py` (`save_maps`):

```
{"schema": 1, "levels": {"1-1": {"width": 2560, "height": 128, "seen": 0.62, "file": "level_1-1.png"}}}
```

`file` is relative to `<source>/maps/`. `seen` is the fraction of columns captured so far (0 to 1). The image is greyscale PNG, `height` rows by `width` columns, columns never seen are white (255). The top-level key is `levels` today. The reader accepts `areas` as an alias for `levels` and no other key, so a later writer can say `areas`; the on-disk Mario writer is NOT changed by this directive.

Ghost track, `<source>/ghosts/<run>.json`, one file per attempt, written atomically and capped at 60 files by oldest-first deletion:

```
{"schema": 1, "game": "mario-land", "run": "1731030000123-2", "agent": "worker-2", "outcome": "death", "every": 2, "points": [["1-1", 12, 88], ["1-1", 14, 88]]}
```

`points` is `[area, x, y]`: `x` is a column in the area image, `y` is a row in the area image (already offset to the image top; may be negative or beyond `height` for a jump above or a fall below, clamp when drawing). `every` is the number of emulator frames between two points. Known outcomes written today are `"death"` and `"best"`; any other string is allowed and means "no death mark".

Read first: `src/pokeagent/world/view.py` (`Viewport`: pan, zoom, `to_screen`, `to_world`, `visible`), `world/zoom.py` (`SNAPS`, `step`, `fit_snap`), `world/pyramid.py` (`Pyramid`: chunked, downscaled textures for huge images, `to_gpu`), `world/follow.py` (`Follow`: ease the camera toward a target). These four are pure or nearly pure and are reused by import only (see the work). `world/model.py` is event-stream based (per-agent HTTP `/events`) and `world/draw.py`, `world/export.py` render Kanto from a ROM; neither is reusable, do not import them. `tests/test_world_view.py` shows how the existing view is tested headless.

## Scope (in this order)

1. `src/pokeagent/mapview/__init__.py` <!-- new: src/pokeagent/mapview/__init__.py --> - one-line docstring.
2. `src/pokeagent/mapview/areas.py` <!-- new: src/pokeagent/mapview/areas.py --> - read the area index and images, tolerant. Under 150 lines.
3. `src/pokeagent/mapview/layout.py` <!-- new: src/pokeagent/mapview/layout.py --> - lay all areas out in one world space. Pure. Under 120 lines.
4. `src/pokeagent/mapview/ghosts.py` <!-- new: src/pokeagent/mapview/ghosts.py --> - read ghost files, tolerant, keep a cache keyed by file mtime. Under 150 lines.
5. `src/pokeagent/mapview/playback.py` <!-- new: src/pokeagent/mapview/playback.py --> - the shared replay clock and per-ghost state at time t. Pure numpy. Under 200 lines.
6. `src/pokeagent/mapview/overlay.py` <!-- new: src/pokeagent/mapview/overlay.py --> - rasterise ghosts, trails and death marks into one RGBA array for the visible rectangle. Pure numpy. Under 200 lines.
7. `src/pokeagent/mapview/best.py` <!-- new: src/pokeagent/mapview/best.py --> - which ghost is "best". Pure. Under 60 lines.
8. `src/pokeagent/mapview/view.py` <!-- new: src/pokeagent/mapview/view.py --> - the Dear PyGui window: canvas, pan and zoom input, texture upload, controls. Under 280 lines.
9. `src/pokeagent/mapview/app.py` <!-- new: src/pokeagent/mapview/app.py --> - `main(argv)`: argument parsing, the refresh thread, the real viewport. Under 150 lines.
10. `tools/map_view.py` <!-- new: tools/map_view.py --> - a 10-line launcher: `uv run python tools/map_view.py runs/mario-land`.
11. Tests, all under `tests/`, listed in the completion criteria.
12. `docs/KNOWLEDGE.md` - a short Map view paragraph (what files it reads, the command).

Do not add a `pokeagent` CLI subcommand in this run (that would touch `src/pokeagent/cli.py`, which directive 2 of the framework plan owns). The launcher in `tools/` is enough.

## The work

### Vocabulary rule

The package `src/pokeagent/mapview/` contains no game-specific terms: no `mario`, `level`, `world` (as a game concept; "world space" for the combined coordinate system is fine only if you call it `space`: use `space`), `pokemon`, `kanto`, `map id`, `lives`, `score`. Say `area`, `agent`, `ghost`, `run`, `outcome`, `point`. The one place the word `levels` appears is the alias lookup in `areas.py`, as the literal dict key `"levels"` with a comment that it is the first writer's key name. A test greps the package for the banned words (see criteria).

### areas.py

- `@dataclass(frozen=True) class Area: name: str; width: int; height: int; seen: float; path: Path`.
- `load_areas(source: Path) -> list[Area]`: read `source / "maps" / "index.json"`; accept `"areas"` or `"levels"`; preserve the order of the index (it is the area order used everywhere); skip an entry whose `file` is missing on disk or whose width or height is not a positive int, with no exception; return `[]` if the index is missing, empty, unreadable or half-written (invalid JSON), never raise.
- `load_image(area: Area) -> np.ndarray | None`: `uint8` RGB array (greyscale expanded to 3 channels), `None` when the file is missing or a partial PNG (Pillow raises `OSError`/`SyntaxError`/`ValueError`: catch exactly those). If the decoded size differs from the index width and height (the index and the image are written separately), trust the image and replace the Area's size via `dataclasses.replace` in the caller, not here.
- `AreaStore`: caches `(mtime_ns, size)` per area file and reloads only what changed; `refresh(source) -> bool` returns True if anything changed. A column of the image that grows between refreshes simply produces a wider image next time.

### layout.py

- `place(areas: list[Area], max_row_width: int = 4096, gap: int = 32, label_h: int = 20) -> Layout` where `Layout` holds `offsets: dict[str, tuple[int, int]]`, `space_w`, `space_h`. Rule: areas are placed in index order left to right in rows; start a new row when the next area would pass `max_row_width`; row height is the tallest area in the row plus `label_h` plus `gap`. An area wider than `max_row_width` gets a row to itself. Deterministic: the same areas give the same offsets, and a NEW area is appended after the existing ones without moving earlier areas' offsets unless the row wraps differently because an earlier area grew; that is accepted, and a test pins the exact offsets for a fixed input.
- `locate(layout, area, x, y) -> tuple[float, float] | None`: space coordinates of a point; `None` for an area not in the layout (a ghost may refer to an area whose map has not been captured yet: such a ghost is simply not drawn until its area arrives).

### ghosts.py

- `@dataclass(frozen=True) class Ghost: run: str; agent: str; outcome: str; every: int; area_idx: np.ndarray (int16, -1 for unknown); xs: np.ndarray (float32); ys: np.ndarray (float32)`, built from `points` once at load; `n` points; `area_names` kept on the store, not per ghost.
- `load_ghost(path) -> Ghost | None`: tolerant: `None` for unreadable, invalid JSON, `schema != 1`, missing keys, `every` not a positive int, `points` empty or containing a malformed entry (drop the whole ghost, do not partially use it; a half-written file is fixed by the next atomic write). Never raise.
- `GhostStore.refresh(source) -> bool`: lists `source / "ghosts" / "*.json"`, parses only new or changed files (mtime and size), forgets files that vanished (the writer caps at 60 and deletes the oldest), returns True on change. Cost per refresh is one `stat` per file plus parsing of the changed ones only.

### playback.py

- The clock: `FPS = 60` named constant (the frame rate that `every` is measured in; documented as "frames per second of the source recording, default 60, overridable with `--fps`"). A ghost's point `i` is at time `i * every / FPS` seconds. Normal speed means the replay clock advances at 1.0 seconds per second.
- `class Clock`: `t` (seconds), `speed` (default 1.0; the controls offer 0.5, 1, 2, 4), `paused`, `loop_gap` (default 1.5 s). `advance(dt)`; the clock loops: when `t` passes the longest visible ghost's duration plus `loop_gap` it returns to 0 and every ghost starts again together. All ghosts therefore start at t = 0 together regardless of when their attempt actually happened ("replayed together").
- `positions(ghosts, t) -> Frame`: for every ghost the index `i = min(n-1, floor(t * FPS / every))`, the area index and `(x, y)` at `i`, a boolean `finished` (t past its last point) and `trail_from` (the index `max(0, i - TRAIL_POINTS)`; `TRAIL_POINTS = 90`, about 3 s at `every=2`). Vectorised over all ghosts with numpy (ghosts of different lengths are padded into 2D arrays when the store changes, not per frame). This function runs in time proportional to the number of ghosts with a small constant and allocates no per-ghost Python objects.

### overlay.py: display cost does not depend on how many ghosts are shown

- `render(frame, ghost_tables, layout, rect, zoom, palette) -> np.ndarray` returns ONE RGBA `uint8` array the size of the visible screen rectangle (never of the whole space). Ghost heads, trail segments and death marks are written into that array with numpy fancy indexing (a head is a filled square of `max(3, int(3 * zoom))` screen pixels; the trail is the sampled trail points drawn as pixels, dimmer with age, capped at `TRAIL_POINTS` per ghost and decimated when the ghost count times trail length passes `MAX_TRAIL_PIXELS = 20000`). The view uploads that one array as ONE texture per UI frame. There are no per-ghost Dear PyGui items and no `draw_*` call per ghost: that is the property that keeps display cost flat as ghosts grow from 5 to 60.
- Colour per agent: a stable colour from the agent string (hash into a small fixed palette defined in this module, no import from `world/draw.py`); the best ghost is drawn in white with a one-pixel dark outline so it stands out.
- Death mark: when a ghost is `finished` and its `outcome` is in `DEATH_OUTCOMES = frozenset({"death", "dead", "died", "fail"})`, draw a cross at its last point; marks persist while that ghost is in the store, so a map shows where attempts ended. Marks for ghosts that are NOT finished yet are not drawn (they have not died yet in replay time). A toggle `show_marks` (default on) hides them.
- A ghost whose current point's area is unknown to the layout is skipped silently (its area image has not arrived).
- Points outside the visible rectangle are discarded before rasterising (a numpy mask).

### best.py

- `best_index(ghosts, area_order) -> int | None`: the ghost with the largest `(area rank, x)` at its LAST point, where area rank is the area's position in the index order; ties go to the shorter ghost (fewer points), then the earlier run id. Ghosts whose last area is unknown to `area_order` rank below all known ones. Returns `None` for no ghosts. This is "furthest reached", chosen over trusting the `outcome == "best"` label because other writers may not produce that label; a ghost labelled `"best"` is NOT special in this module.

### view.py and app.py: the window

- Reuse by import, unchanged: `pokeagent.world.view.Viewport` (pan/zoom/to_screen/to_world/visible, snap zoom), `pokeagent.world.zoom` (`SNAPS`, `step`), `pokeagent.world.pyramid.Pyramid` and `to_gpu` (chunked texture levels for large stitched images), `pokeagent.world.follow.Follow` (`target`, `step`). If any of these cannot be imported without pulling in the Kanto render code (check `git grep -n "^from\|^import" src/pokeagent/world/{view,zoom,pyramid,follow}.py` first), do not import it: write the small piece you need inside `mapview/` instead and say so in the Report. `src/pokeagent/world/` must have no diff at all at the end (criterion).
- The base image of all areas is composed ONCE into one `uint8` RGB array of the layout's size (white background, a label strip with the area name above each area drawn with the Dear PyGui default font only through a text item, not baked into pixels). Rebuild the base only when the `AreaStore` or layout changes, then wrap it with `Pyramid`. A space larger than 8192 px per side is exactly the case `Pyramid` chunks.
- Pan with left-drag, zoom with the mouse wheel at the cursor (`step_zoom_at`), a Fit button, a 1:1 button. Zoom snaps to `world.zoom.SNAPS`. Missing-column regions (white) are shown as they are; the area's `seen` fraction is shown in its label text as a percentage.
- Controls row: play/pause, speed (0.5, 1, 2, 4), trails on/off, death marks on/off, Follow best on/off. An agent list (a small table, one row per distinct agent: colour swatch, agent, number of ghosts, furthest reached) with a click to follow that agent's best ghost. The table is built from the store, not per frame.
- Follow best: `Follow.start(<best ghost run>, now)`; the camera eases to that ghost's current space position each frame; follow stops when the user pans (existing behaviour of the Viewport/Follow pair) or the best ghost changes (then it re-targets automatically while the option is on).
- Live refresh: `app.py` runs one daemon thread that calls `AreaStore.refresh` and `GhostStore.refresh` every `REFRESH_S = 2.0` seconds and swaps a new immutable snapshot (areas, layout, ghost tables) into a holder under a lock; the UI thread only reads the holder. New ghost files appear in the replay on the next loop start (never mid-loop, so the shared clock stays consistent); new or wider area images appear on the next base rebuild and the camera does not jump (the Viewport keeps its centre and zoom). If the source directory does not exist yet, the window opens with an empty-state message ("waiting for <dir>") and starts working when it appears.
- Argument: `uv run python tools/map_view.py runs/mario-land [--fps 60] [--refresh 2.0]`; the source directory is the one positional argument and nothing in it is assumed other than `maps/index.json` + images and `ghosts/*.json`.
- The window class takes the already-built snapshot and an explicit `headless: bool`. Creating the Dear PyGui viewport lives only in `app.py:run()`, which no test calls.

## What NOT to do

- Do not change anything under `src/pokeagent/world/` (no edit, no rename, no new file). Pokemon's world view behaviour must be identical; `git diff --stat main -- src/pokeagent/world` must be empty.
- Do not read or write any Pokemon structure (`maps.json`, `runs/agents`, the control API, shared-memory frames). This view reads only `<source>/maps/` and `<source>/ghosts/`.
- Do not touch `tools/mario_maps.py`, `tools/watch_game.py`, `tools/watch_mario_land.py` or any other Mario file: the Mario writers stay as PR #169 left them.
- Do not touch `roms/`, `baselines/`, or any ROM data, and do not state where any game copy came from, in code, comments, docs or the report.
- Do not add a dependency; Dear PyGui, numpy and Pillow are already installed.
- Do not add a pokeagent CLI subcommand, do not edit `src/pokeagent/cli.py`, and do not touch `GameSpec` or any other directive's scope.
- No per-ghost Dear PyGui items; one texture for all ghosts is the contract.
- No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- A test must never create a viewport, never send input, never show a window.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_mapview_areas.py tests/test_mapview_layout.py tests/test_mapview_ghosts.py tests/test_mapview_playback.py tests/test_mapview_overlay.py tests/test_mapview_best.py tests/test_mapview_window.py tests/test_mapview_vocabulary.py
```
Expected: all pass.

```
uv run pytest -q tests/test_world_view.py tests/test_world_follow.py tests/test_viewer_tiles_world.py
```
Expected: same result as before the change (the one ROM-gated skip in `test_world_view.py` stays).

```
git diff --stat main -- src/pokeagent/world tools/mario_maps.py tools/watch_game.py
```
Expected: no output.

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree (no ROM is present, none is needed).

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Tests are headless: `dpg.create_context()` and `dpg.destroy_context()` only. No `create_viewport`, no `show_viewport`, no `setup_dearpygui`, no input events, nothing may open a window on Robert's screen. Anything that needs a real window is a pure function you test directly, or is listed under "Required from User".
- Fixtures are small synthetic files generated inside the test with `tmp_path`: an index and 2 or 3 tiny PNGs (for example 60x20 greyscale with a gradient), and ghost JSON files of 5 to 40 points. No fixture file is committed and none is read from `runs/`.
- Branch only (`directive/pokeagent-game-map-view-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, the test tails and the line counts of the new files in the Report.

## Completion criteria

- [ ] `load_areas` reads the Mario index shape (`levels`) and the `areas` alias, keeps index order, and skips entries with a missing file or bad size; invalid JSON, an empty file and a missing directory each return `[]` without raising. <!-- test: tests/test_mapview_areas.py -->
- [ ] `load_image` returns `None` for a missing file and for a truncated PNG, and an RGB array for a valid greyscale PNG; `AreaStore.refresh` reports a change when a file is rewritten wider and not otherwise. <!-- test: tests/test_mapview_areas.py -->
- [ ] `place` returns the pinned offsets for a fixed 5-area input, wraps rows at `max_row_width`, gives an over-wide area its own row, and `locate` returns `None` for an unknown area. <!-- test: tests/test_mapview_layout.py -->
- [ ] `load_ghost` accepts a valid schema-1 file, and returns `None` (no raise) for truncated JSON, wrong schema, missing keys, `every` of 0, empty points and a malformed point; `GhostStore.refresh` picks up a new file, drops a deleted one, and re-parses only a changed one (assert the parse count). <!-- test: tests/test_mapview_ghosts.py -->
- [ ] `positions` at `t = 0` puts every ghost at its first point and at `t = i * every / FPS` at point `i`; ghosts of different lengths stay at their last point with `finished` true; `Clock` loops back to 0 after the longest ghost plus the gap; speed 2 advances twice as fast. <!-- test: tests/test_mapview_playback.py -->
- [ ] `render` returns an array exactly the size of the visible rectangle; a ghost head appears at the expected pixel; a death mark appears only after a ghost with a death outcome has finished; a ghost in an area missing from the layout draws nothing; and the call time for 60 ghosts is under 3 times the call time for 5 ghosts on the same rectangle (a ratio check with `time.perf_counter`, generous bound, to show cost is not per ghost). <!-- test: tests/test_mapview_overlay.py -->
- [ ] `best_index` picks the ghost furthest by area order then x, breaks ties to the shorter ghost then the earlier run, ranks unknown-area ghosts last, and returns `None` for none; a ghost labelled `"best"` that is not furthest is not chosen. <!-- test: tests/test_mapview_best.py -->
- [ ] The window builds headless from synthetic files after `dpg.create_context()`: base image composed once, the one overlay texture updated per frame, the agent table has one row per distinct agent, Follow best moves the Viewport centre toward the best ghost, and an empty source directory gives the empty-state message instead of an error; the test never creates a viewport. <!-- test: tests/test_mapview_window.py -->
- [ ] A live-refresh test writes a new ghost file and a wider area image into the source directory while a snapshot holder is in use, calls the refresh function once, and the next snapshot contains both without the camera centre or zoom changing; a half-written (truncated) ghost file written at the same time is ignored and does not raise. <!-- test: tests/test_mapview_window.py -->
- [ ] `src/pokeagent/mapview/` contains none of the banned words (`mario`, `pokemon`, `kanto`, `lives`, `score`, `map_id`, `level` except the single alias key in `areas.py`), and every file is under its stated line limit. <!-- test: tests/test_mapview_vocabulary.py -->
- [ ] `git diff --stat main -- src/pokeagent/world` is empty and the existing world tests pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, the line count of each new file, which `world/` pieces were reused by import and which (if any) had to be rewritten in `mapview/` and why, the constants chosen (`FPS`, `TRAIL_POINTS`, `MAX_TRAIL_PIXELS`, `REFRESH_S`, `max_row_width`), and the real-window checklist for Robert (below).

Real-window checklist (Robert, not Devin; the Claude verify lane cannot open a window on his screen either): run the Mario watcher so `runs/mario-land/` fills, then `uv run python tools/map_view.py runs/mario-land`, and check: (1) every level appears once, labelled, and you can pan and zoom to read a gap; (2) all ghosts move together at normal speed and the frame rate does not drop as ghosts increase; (3) death crosses appear where attempts ended; (4) Follow best keeps the camera on the furthest ghost; (5) new ghosts and wider columns appear within a few seconds without the view jumping.

## Forbidden Actions

- Do not touch `roms/`, `baselines/` or any ROM data, and do not state where a game copy came from.
- Do not edit anything under `src/pokeagent/world/`, `src/pokeagent/cli.py`, `src/pokeagent/emulator.py`, or any Mario file under `tools/`.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a Dear PyGui viewport, send input, or open any window in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The real-window check in the Report section, after the Claude verify lane passes. Robert runs it; nothing here blocks the run.
- PR #169 merged to main before dispatch (or the run branched from a base that contains it).

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
| Branch | directive/pokeagent-game-map-view-directive |
| Base branch | - |
| Base commit | 4b6b9da5a4621f24f6d73caf4557f36aac3da593 |

**Status log**
- 2026-11-08 12:16 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert: game-agnostic Map view (plan V3); needs PR #169 on main
- 2026-11-08 12:19 · robert-claude-laptop · Queued → Approved — lint override: False positives: the four tests/test_mapview_*.py files are created by this run, and maps/index.json is generated run output under the source directory argument, not a repo path.
- 2026-11-08 12:35 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-game-map-view-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6Y3NBNFS330M5C5HZAZEW25
<!-- queue:end -->
