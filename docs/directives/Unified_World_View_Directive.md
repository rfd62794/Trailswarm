# PokeAgent: World view picks its renderer from the game's preset, so Mario's stitched maps and Pokemon's Kanto share one window, one agent list and one selection

## Why this exists

Robert, 2026-11-08: "Can I get the two views merged and aligned? ... the Game View and Map View are not following the same Agents. Can we take steps to make this behave closer to the Pokemon Red View System we've built."

Robert's design decision, 2026-11-08: "For Mario, Map and World are the same view, not a third view." So there is NO new mode: the viewer keeps its two modes, Tiles and World, and World mode chooses its renderer from the game's view preset. For Pokemon Red the renderer is the existing Kanto World renderer, unchanged. For Mario and any game with stitched areas it is the `mapview` renderer, in the same window, with the same agent list and focus panel, and one selection driving camera and game panel. User-facing labels say "World", never "Map".

Today there are two windows. `tools/watch_game.py` (or the `pokeagent view` Tiles/World window) shows the live emulator; `tools/map_view.py` (PR #172, `src/pokeagent/mapview/`) shows the stitched maps with ghosts. They share no selection, no agent list and no clock. The Pokemon view already solves this inside one window: `src/pokeagent/viewer/ui/window.py` `ViewerWindow` holds one `self.selected`, `FocusState` in `src/pokeagent/viewer/layout.py` picks the mode, `WorldHost` (`viewer/ui/world_host.py`) wires the World mode in, and `modes.status_text` names the selected agent in one status line.

**Depends on directive 1** (`docs/directives/Game_View_Presets_And_Avatars_Directive.md`): the live position files (`<source>/live/<agent>.json`, `mapview/live.py`), `mapview/presets.py` and `mapview/avatars.py`. This run must start from a main that contains PRs #171 and #172 AND directive 1's merge. Check with `git grep -n "class LiveStore" -- src/pokeagent/mapview/live.py` and `git grep -n "def resolve" -- src/pokeagent/mapview/presets.py`. If either finds nothing, stop and write that in the Status row; do not recreate them.

Facts about the code, pasted because the worktree cannot be searched for them reliably:

- `viewer/modes.py`: `CHOICES = ("tiles", "world")` and it STAYS that way, `_TO_INTERNAL = {"tiles": "grid", "world": "world"}`, `_LABEL = {"grid": "Tiles", "world": "World", "focus": "Focus"}`, `status_text(view, agents, selected, follow_id)` returns `"Mode: ... | Agents: N | Selected: X | Follow: off"`.
- `viewer/layout.py` `FocusState`: `MODES = ("grid", "world")` (unchanged); `set_mode` ignores unknown modes and does nothing while an agent is focused; `view` is `"focus"` while focused else `mode`.
- `viewer/app.py`: `main(argv)` parses `--root`, `--fake N`, `--web`, `--port`, `--fps`, `--mode {tiles,world}`; `run(root, fps, fake, web, web_port, world_mode, mode)` builds `ViewerModel`, `WorldModel`, the poller thread, then `ViewerWindow(...)` and calls `win.focus.set_mode(modes.internal(mode))`. There is NO positional source argument today; the registry root is `--root`. `src/pokeagent/cli.py` defines `pokeagent view` (`--root --fake --web --port --fps --mode {tiles,world}`, `set_defaults(func=_cmd_view)`) and `pokeagent world` (defined in `src/pokeagent/world/app.py` `add_parser`, which calls `viewer.app.run(args.root, fake=args.fake, mode=args.mode)`); `world/` is off limits, so the new arguments go on `pokeagent view` only.
- `viewer/model.py` `ViewerModel`: `ids()`, `snapshot(agent_id)`, `frame(agent_id)` returns `(rgb_bytes, w, h)` or `None`, `staleness(agent_id)`, and `set_wants(focused, frames)` / `want_frames(frames, ttl_s)`: the poller only fetches frames for the focused agent and the agents asked for through these calls. The gameplay panel must therefore ask for its selected agent's frames every frame it is visible.
- `viewer/ui/window.py` is 282 lines and `viewer/ui/world_view.py` is 282 lines: both are over any comfortable size. Do NOT grow either. New wiring goes in new files; `window.py` gains at most a few lines (a `StitchedHost` member and its tick/fit/visibility calls, mirroring `self.world = WorldHost(self, world)`).
- `mapview/view.py` `MapWindow` (#172, 279 of 280 lines; directive 1 may have extracted `controls.py`): takes an immutable snapshot and `headless: bool`; has `adopt(snap)`, `build(parent)`, `resize(w, h)`, `tick(dt, now)`, follow-best, follow-agent via the agent table, pan disabling follow, one overlay texture. `mapview/app.py` has `Snapshot`, `Holder`, `snapshot_once`, `poll_loop`, `REFRESH_S`, `run(source)` (creates its own viewport) and `main(argv)`.
- `tools/map_view.py` is a 12-line launcher for `mapview.app.main`.

Read first: `src/pokeagent/viewer/app.py`, `viewer/modes.py`, `viewer/layout.py`, `viewer/ui/window.py`, `viewer/ui/world_host.py`, `viewer/ui/world_side.py` (how the World side panel binds the agent list and focus), `viewer/ui/card.py` (how a frame is turned into a texture; reuse its helper if it has one rather than writing a second one), `src/pokeagent/mapview/app.py`, `mapview/view.py`, `mapview/live.py`, `mapview/presets.py`, `tests/test_viewer_tiles_world.py` (how the viewer is tested headless).

## Scope (in this order)

1. `src/pokeagent/viewer/selection.py` <!-- new: src/pokeagent/viewer/selection.py --> - the single selection, pure. Under 120 lines.
2. `src/pokeagent/mapview/pick.py` <!-- new: src/pokeagent/mapview/pick.py --> - click to agent hit test, pure. Under 80 lines.
3. `src/pokeagent/mapview/view.py` (and `controls.py` if directive 1 made it) - `on_pick` callback, `set_selected`, `selected` drives follow (edit). `view.py` MUST NOT exceed 280 lines; if it needs lines, extract existing mouse handling into `src/pokeagent/mapview/pointer.py` <!-- new: src/pokeagent/mapview/pointer.py --> (under 90 lines) with no behaviour change.
4. `src/pokeagent/mapview/presets.py` - add the `world_renderer` field to `Preset` and its values in the tables (edit; directive 1 owns the file, this adds one field). Values: `"rom-world"` or `"stitched"`. Defaults: `rpg-overworld` and `pokemon-red` are `"rom-world"`; `platformer`, `flip-screen` and `super-mario-land` are `"stitched"`.
5. `src/pokeagent/viewer/renderer_choice.py` <!-- new: src/pokeagent/viewer/renderer_choice.py --> - pure: which World renderer to use. Under 50 lines.
6. `src/pokeagent/viewer/stitched_source.py` <!-- new: src/pokeagent/viewer/stitched_source.py --> - owns the map source directory, its snapshot refresh thread and the `frame_for` bridge to the viewer's frame source. Under 110 lines.
7. `src/pokeagent/viewer/ui/stitched_host.py` <!-- new: src/pokeagent/viewer/ui/stitched_host.py --> - build, fit and tick of the stitched renderer inside World mode, mirroring `WorldHost`. Under 120 lines.
8. `src/pokeagent/viewer/ui/stitched_side.py` <!-- new: src/pokeagent/viewer/ui/stitched_side.py --> - the focus panel (selected agent's gameplay frame, notice, status) and the agent list. Under 180 lines.
9. `src/pokeagent/viewer/ui/window.py` - wire `StitchedHost` into World mode (edit, a few lines).
10. `src/pokeagent/viewer/app.py` - `--source`, `--game`, `--preset`, `--genre` arguments, build the stitched source when the chosen renderer is `stitched` (edit, stays small).
11. `src/pokeagent/cli.py` - add the four arguments to the `view` parser and forward them to `viewer.app.run` (edit, under 12 lines; the only permitted `cli.py` change).
11b. `tools/map_view.py` - thin launcher onto the unified viewer (edit).
12. Tests, all new: <!-- new: tests/test_viewer_selection.py --> <!-- new: tests/test_mapview_pick.py --> <!-- new: tests/test_viewer_world_stitched.py --> <!-- new: tests/test_viewer_stitched_source.py --> <!-- new: tests/test_viewer_renderer_choice.py --> <!-- new: tests/test_map_view_launcher.py -->. Existing, must stay green (from PR #172, present once it is on main): `tests/test_mapview_window.py`, `tests/test_mapview_overlay.py`, `tests/test_mapview_vocabulary.py`.
13. `docs/KNOWLEDGE.md` - a short paragraph: World's two renderers, the selection rule, the launch command.

## The work

### The launch command and the renderer choice (decision recorded here)

`pokeagent world` is defined in `world/app.py`, which is off limits, and it already forwards to `viewer.app.run`; `pokeagent view` is defined in `cli.py` and is where the arguments can be added. So the entry is: `uv run pokeagent view --mode world --source runs/mario-land [--game super-mario-land]`, with `--root` unchanged (the agent registry). `--game`, `--preset` and `--genre` go to `mapview.presets.resolve`; `--source` is the directory holding `maps/`, `ghosts/`, `live/`.

`renderer_choice.choose(preset, source: Path | None) -> "rom-world" | "stitched"` is pure: no `--source` means `"rom-world"` always (so every existing launch is unchanged); with a source, the preset's `world_renderer` decides (an unknown preset falls back through `resolve` as in directive 1). `viewer.app.run` calls it once and builds `WorldHost` (rom-world) or `StitchedHost` (stitched) as World mode's content; Tiles is untouched. `tools/map_view.py runs/mario-land [--game NAME]` becomes a thin launcher that calls `pokeagent.viewer.app.main(["--mode", "world", "--source", <dir>, ...])`: one window. The old standalone `mapview.app.main` stays importable and its tests stay green; the launcher no longer calls it.

### selection.py: one selection drives everything (pure)

- `class Selection`: `agent: str | None`, `source: "auto" | "user"`, `is_live: bool`.
- `featured(live: dict[str, LivePos], registry_ids: list[str]) -> str | None`: the agent with the freshest live file whose id is in `registry_ids`; else the first registry id; else `None`. A live record for an agent that is not in the registry (the live agent should be the registry card, see `mario-land`) is ignored for featuring but still drawn on the map.
- `Selection.update(live, registry_ids)`: while `source == "auto"` the selection follows `featured`; once the user clicks (`select(agent, kind)`), `source` becomes `"user"` and it stays until the user picks "Auto" again, or the selected agent is a registry card that disappeared (then back to auto).
- `select(agent_id, kind)`: `kind` is `"live"` (a registry agent) or `"ghost"` (an agent name that appears only in ghost files).
- `gameplay_agent(sel, registry_ids, featured_id) -> tuple[str | None, str]`: which registry agent the gameplay panel shows and a notice. A live selection shows itself with notice `""`. A ghost-only selection keeps showing `featured_id` and the notice is exactly `f"{agent}: recorded run, no live frames - showing {featured_id}"` (replay on demand is OUT OF SCOPE; do not build it). No registry agent at all: `(None, "no live agent")`.
- `camera_target(sel, live, best_ghost_pos_for) -> tuple[float, float] | None`: the space position to follow: for a live selection the live record's position via `layout.locate`; for a ghost selection the current position of that agent's best ghost; `None` if neither is known (the camera stays).
- No Dear PyGui import in this module.

### pick.py

- `pick_agent(px, py, drawn: list[tuple[str, str, float, float]], radius: float = 10.0) -> tuple[str, str] | None`: `drawn` is `(agent, kind, screen_x, screen_y)` for every avatar the overlay drew this frame (the overlay already knows them; add a method `overlay.heads(...)` or return them from `render` WITHOUT adding a per-ghost Dear PyGui item; if `render`'s signature has to change, change it so existing callers and tests still work). Nearest within `radius`; live beats ghost on a tie; `None` otherwise.

### MapWindow changes

- `MapWindow` takes `on_pick: Callable[[str, str], None] | None`. A click (press and release within 4 px, so a drag does not select) calls `pick_agent` and then `on_pick`. `set_selected(agent, kind)` sets what the camera follows through `selection.camera_target`; the map's own `Follow best` / `Follow live` checkboxes are replaced by one `Follow selected` checkbox (default on). Pan disables follow (the #172 fix; keep it and test it again for the unified mode). The map's own agent table is hidden in the unified mode (the agent list lives in `stitched_side.py`); the standalone window keeps its table.
- The selected agent's avatar gets a 2 px highlight ring on the overlay.

### The unified layout (same shape as the Pokemon view)

- `stitched_host.py` mirrors `WorldHost`: `build()`, `fit(vw, avail)`, `tick()`; the area is shown only when `focus.view == "world"` and the chosen renderer is `stitched`. Layout: a large map on the left, a right-hand column at about 28 percent of the width (minimum 280 px) with the focus panel on top and the agent list below, the whole thing sharing the window with the existing control bar and status line. Use `viewer.ui_scale.px` for sizes like the other panels.
- `stitched_side.py` focus panel: the selected-gameplay agent's current frame (reuse `card.py`'s frame-to-texture helper; scale to fit the panel keeping aspect, integer upscale when it fits), under it the status line from `modes.status_text` AND the notice from `gameplay_agent`, AND the preset's `status_fields` values from that agent's snapshot when present. It calls `model.set_wants(...)` / `want_frames(...)` for the displayed agent every tick so frames keep coming. When there is no frame yet it shows the existing `panels/noframe.py` text.
- Agent list: one row per live registry agent (colour swatch from the map's agent colour, id, state) followed by one row per ghost-only agent (swatch, name, ghost count, furthest reached, "recorded" tag); the selected row is highlighted; click selects (same `Selection.select`); an "Auto" button returns to featured. Built from stores, not per frame (rebuild only when the set of rows changes).
- Status line: `ViewerWindow.status_line` shows the selection in World mode with the stitched renderer: `Mode: World  |  Agents: N  |  Selected: <agent>  |  Follow: on (<agent>)`. `modes.py` and `FocusState` are NOT changed: no new mode, no new label.
- Default selection is the live featured agent, so on launch the gameplay panel and the map camera are on the same agent without a click. That is the acceptance test for the complaint.
- The existing mode switch (Tab and the menu in `viewer/ui/menu.py` and `keys.py`) is unchanged and still toggles Tiles and World; switching never loses `Selection`.
- The stitched renderer lays areas out with the preset's `area_gap_px` and draws the preset's coloured edge lines (both built in directive 1: `layout.place(gap=...)`, `edges.edge_colours`, `edges.draw_edges`); this run only passes the resolved preset through. Clicks, camera follow and the selection use the same layout offsets, so they already include the gap.
- The avatar cache of directive 1 is fed from the viewer's live frame of the featured agent: `stitched_source.frame_for(agent)` returns `model.frame(agent)` for a registry agent and `None` otherwise (this is the `frame_for` hook directive 1 left open). The avatar therefore appears in the unified window without any new capture path.

### World mode and Pokemon Red: unchanged

World mode, `WorldHost`, `world/` and `atlas/` get no edits. The stitched renderer is additive: a window started without `--source` behaves exactly as before, and a Pokemon Red preset keeps the Kanto renderer even with a source. Moving Pokemon Red onto the stitched renderer is a later step; do not start it.

## What NOT to do

- Do not edit anything under `src/pokeagent/world/` or `src/pokeagent/atlas/`, `viewer/ui/world_host.py`, `viewer/ui/world_view.py`, `viewer/ui/world_side.py`: the World mode must not regress. `git diff --stat main -- src/pokeagent/world src/pokeagent/atlas src/pokeagent/viewer/ui/world_*.py` must be empty.
- Do not build replay-on-demand for a recorded ghost, a second emulator, or any new frame capture path.
- Do not add game words to `viewer/` or `mapview/` outside `mapview/presets.py`; the vocabulary test of #172 still passes.
- Do not grow `window.py` or `world_view.py` by more than 10 lines; do not grow `mapview/view.py` past 280.
- Do not persist extracted art (the avatar crops stay in memory); do not read, print or state where any game copy came from.
- Do not touch `roms/`, `baselines/`, any ROM data, any Mario file under `tools/`, or `src/pokeagent/cli.py` beyond the four added `view` arguments.
- Do not add a dependency.
- No scratch or debug files outside `.devin-scratch/`; deleting is denied in the sandbox.
- A test never creates a viewport, never sends input, never opens a window.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_viewer_selection.py tests/test_mapview_pick.py tests/test_viewer_world_stitched.py tests/test_viewer_stitched_source.py tests/test_viewer_renderer_choice.py tests/test_map_view_launcher.py
```
Expected: all pass.

```
uv run pytest -q tests/test_viewer_tiles_world.py tests/test_world_view.py tests/test_world_follow.py tests/test_viewer_core.py tests/test_viewer_focus_steering.py tests/test_viewer_layout_file.py
```
Expected: same result as on main (the existing Tiles and World behaviour does not regress).

```
uv run pytest -q tests/test_mapview_window.py tests/test_mapview_overlay.py tests/test_mapview_vocabulary.py
```
Expected: pass unchanged.

```
git diff --stat main -- src/pokeagent/world src/pokeagent/atlas src/pokeagent/viewer/ui/world_host.py src/pokeagent/viewer/ui/world_view.py src/pokeagent/viewer/ui/world_side.py
```
Expected: no output.

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Tests are headless: `dpg.create_context()` and `dpg.destroy_context()` at most. No `create_viewport`, no `show_viewport`, no `setup_dearpygui`, no input events, nothing may open a window on Robert's screen. Mouse behaviour is tested by calling the pure functions (`pick_agent`, the click-versus-drag decision, `Selection`) directly.
- Fixtures are synthetic: a `ViewerModel` fed by fake sources (see `_AnimatedFake` in `viewer/app.py` and the fakes in `tests/test_viewer_tiles_world.py`), live and ghost JSON written under `tmp_path`, small synthetic PNG maps. No ROM, no `runs/`.
- Branch only (`directive/pokeagent-unified-map-mode-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Done for the Status row means `Review`, with the diff stat, test tails, new-file line counts and every decision made where this directive was silent, in the Report.

## Completion criteria

- [ ] `featured` picks the freshest live registry agent, falls back to the first registry id, then `None`; `Selection.update` follows `featured` while `source == "auto"`, a `select` call makes it sticky, "Auto" releases it, a vanished selected registry agent returns to auto; `gameplay_agent` returns the agent itself for a live selection, returns the featured agent plus the exact notice text for a ghost-only selection, and `(None, "no live agent")` with an empty registry; `camera_target` returns the live position for a live selection, the best-ghost position for a ghost selection, and `None` when unknown. <!-- test: tests/test_viewer_selection.py -->
- [ ] `pick_agent` returns the nearest agent within the radius, prefers live on a tie, and returns `None` outside; a press and release within 4 px counts as a click and one that moved more does not. <!-- test: tests/test_mapview_pick.py -->
- [ ] `modes.CHOICES`, `FocusState.MODES` and the labels are unchanged (assert the exact tuples); `renderer_choice.choose` returns `"rom-world"` with no source for every preset, `"rom-world"` for `pokemon-red` and `rpg-overworld` with a source, `"stitched"` for `super-mario-land`, `platformer` and `flip-screen` with a source, and falls back without raising for an unknown preset; the `world_renderer` field is in every genre and game row. <!-- test: tests/test_viewer_renderer_choice.py -->
- [ ] In the stitched World view the layout is built with the preset's `area_gap_px`, the base carries the edge lines (the base image differs from the no-edge base only in the gap ring), and a click on a ghost placed in the second area hits it at the gap-shifted screen position; the camera target for the selected agent equals `layout.locate` of its position. <!-- test: tests/test_viewer_world_stitched.py -->
- [ ] A headless window built from fake viewer agents and a synthetic source in World mode with the stitched renderer: the default selection is the live featured agent, the map camera target and the gameplay panel agent are that same agent, clicking a ghost-only agent in the list changes the camera target to that ghost and leaves the gameplay panel on the featured agent with the exact notice, "Auto" restores the featured agent for both, panning disables follow and a pick re-enables it, and `status_line` names the selected agent. <!-- test: tests/test_viewer_world_stitched.py -->
- [ ] `stitched_source` refresh picks up a new live file and a new ghost file in the next snapshot, ignores a truncated ghost file, treats a stale live file as absent, and `frame_for` returns the model's frame for a registry agent and `None` for a ghost-only agent; the viewer asks for frames for the displayed agent (assert `want_frames` is called with that id). <!-- test: tests/test_viewer_stitched_source.py -->
- [ ] `tools/map_view.py runs/x --game g` builds the argument list `["--mode", "world", "--source", "runs/x", "--game", "g"]` and hands it to `viewer.app.main` (test patches `main` and asserts the call; no window); `viewer.app.main` parses `--source`, `--game`, `--preset`, `--genre`, accepts the four new arguments on `pokeagent view` through `cli.py`, and a call without `--source` behaves as before (rom-world renderer). <!-- test: tests/test_map_view_launcher.py -->
- [ ] Existing Tiles and World tests, the #172 mapview tests and the vocabulary test pass unchanged; `git diff --stat main -- src/pokeagent/world src/pokeagent/atlas src/pokeagent/viewer/ui/world_host.py src/pokeagent/viewer/ui/world_view.py src/pokeagent/viewer/ui/world_side.py` is empty; `window.py` grew by at most 10 lines and `mapview/view.py` is at most 280.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat; test tails; line count of each new file against its limit; decisions made where this directive was silent (anything extracted from `view.py`, how `run` forwards the new arguments); and the real-window checklist below.

Real-window checklist (Claude, in a real window; Devin cannot do it): with the Mario display and workers running, `uv run pokeagent view --mode world --source runs/mario-land --game super-mario-land`: (1) one window with the map large, the focus panel and the agent list at the right; (2) on launch the gameplay panel and the map camera are on the same agent without a click, and that agent is the live Mario with a Mario-shaped avatar; (3) clicking a ghost moves the camera to it, the status line names it, and the gameplay panel keeps the featured agent with the "recorded run, no live frames" notice; (4) "Auto" returns both to the live agent; (5) dragging the map stops the camera following; (6) switching Tiles and World and back keeps the selection; (7) a Pokemon Red run in World mode looks and behaves exactly as before; (8) the frame rate with 60 ghosts is steady; (9) the stacked areas have a thin gap and coloured edge lines in the World view, adjacent areas clearly different.

## Forbidden Actions

- Do not touch `roms/`, `baselines/` or any ROM data, do not persist extracted art, and do not state where a game copy came from.
- Do not edit anything under `src/pokeagent/world/`, `src/pokeagent/atlas/`, the three `viewer/ui/world_*.py` files named above, `src/pokeagent/cli.py` beyond the four added `view` arguments, `src/pokeagent/emulator.py`, or any Mario file under `tools/`.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a Dear PyGui viewport, send input, or open any window in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The real-window checklist above, after the Claude verify lane passes; Claude runs it. Nothing here blocks the run.
- PRs #171 and #172 and directive 1 (`Game_View_Presets_And_Avatars_Directive.md`) merged to main before dispatch.

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
| Branch | directive/pokeagent-unified-world-view-directive |
| Base branch | - |
| Base commit | 500782e9ebaca45a786b0aa57fcdcda18760df27 |
| Head commit | 1454c6edc6deb374ba2f1dbf9fb785310500b9e2 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-08 13:36 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert: World view picks renderer from preset; depends on Game_View_Presets_And_Avatars and PRs 171/172 on main
- 2026-11-09 22:36 · robert-claude-laptop · Queued → Approved
- 2026-11-09 22:37 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-unified-world-view-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M71RFYM6T0EC0KTG68KM8FPV
- 2026-11-09 22:41 · dispatcher · launched pid=22976; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-unified-world-view-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (4 declared need(s), repo-scoped only))
- 2026-11-09 23:36 · devin · In progress → Review — DONE bffa8b9 on directive/pokeagent-unified-world-view-directive, pushed (24 files, +1181/-71). DIFF STAT: world/, atlas/, viewer/ui/world_*.py diff vs main is EMPTY (verified). window.py 282->286 (+4, cap +10). mapview/view.py exactly 280 (cap 280). NEW FILES vs limits: viewer/selection.py 74/120, mapview/pick.py 59/80, mapview/pointer.py 56/90, viewer/renderer_choice.py 19/50, viewer/stitched_source.py 68/110, viewer/ui/stitched_host.py 100/120, viewer/ui/stitched_side.py 131/180, tests x6. TEST TAILS (real output): new tests `uv run pytest -q tests/test_viewer_selection.py tests/test_mapview_pick.py tests/test_viewer_world_stitched.py tests/test_viewer_stitched_source.py tests/test_viewer_renderer_choice.py tests/test_map_view_launcher.py` -> 29 passed. Tiles/World regression group -> 66 passed, 1 skipped. mapview group (window/overlay/vocabulary) -> 21 passed. `uv run python --version` -> Python 3.12.12. FULL SUITE CAVEAT: `uv run pytest -q` ran >40 min in background without producing a tail (stdout buffered past 12%). The alphabetically surrounding files were run standalone (test_ab..test_area_resistance, test_atlas, test_atlas_rom, test_backend, test_battle_log_fidelity, test_battle_text_wait): 114 tests, all pass in <3 s, so the stall region is unrelated to this diff. Recommend re-running the full suite in the verify lane. DECISIONS where the directive was silent: (1) heads() lives in mapview/pick.py not overlay.py — adding ~20 lines to overlay.py would have broken its 200-line vocabulary cap; pick.py cap is 80. (2) camera_target's `live` arg is the already-located space-position dict (caller runs layout.locate) since the fixed signature has no layout parameter. (3) follow_best flag is reused as the 'Follow selected' checkbox state in unified mode rather than a third flag. (4) MapWindow._follow_agent moved to controls.follow_agent to keep view.py <=280; pointer.py holds mouse handling. (5) overlay.render gained a `selected=(agent,kind)` kwarg drawing a 2 px agent-colour ring. (6) StitchedHost.follow() only converts a DIFFERENT agent into a user pick so re-entering World keeps auto selections auto. (7) run() forwards via a small _stitched_source() helper that resolves the preset, calls renderer_choice.choose once, and starts the refresh threads (threads are not started in tests). (8) tools/map_view.py emits POSIX paths so the argv list is exact on Windows. (9) Fixed avatars.feed to accept bytes frames via np.frombuffer — np.asarray(bytes,uint8) raises on this numpy version and the avatar cache could never fill. Launcher contract verified: args_for('runs/x','g') == ['--mode','world','--source','runs/x','--game','g']; cli.py gained exactly the four view arguments. No viewport/input/window opened by any test (create_context/destroy_context only). [origin] spent: devin 55 min est. n/a
- 2026-11-10 07:13 · robert-claude-laptop · Review → Blocked — Row head bffa8b9 is stale after review fixes; branch head is 8e58b84. Re-resolving the head so verify runs against it.
- 2026-11-10 07:13 · robert-claude-laptop · Blocked → Review — Head re-resolved to 8e58b84 after review fixes; independent re-review APPROVE on PR #186. [origin] spent: devin 55 min est. n/a
- 2026-11-10 07:19 · robert-claude-laptop · Review → Blocked — Row head 8e58b84 is stale; branch head is 1454c6e after merging main and one test scope fix. Re-resolving the head.
- 2026-11-10 07:19 · robert-claude-laptop · Blocked → Review — Head re-resolved to 1454c6e; review of the merge and test scope change recorded on PR #186. [origin] spent: devin 55 min est. n/a
- 2026-11-10 07:22 · robert-claude-laptop · Review → Done — note: PR #186 merged; independent review APPROVE; full verify at 1454c6e 2323 passed, 0 failed, 41 known skips.
<!-- queue:end -->
