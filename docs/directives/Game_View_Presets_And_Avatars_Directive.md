# PokeAgent: Map view gets a live-position contract, game presets and real avatars instead of dots

## Why this exists

Robert, 2026-11-08: "the Map view doesn't show Mario, just a dot. And the Game View and Map View are not following the same Agents. Can we take steps to make this behave closer to the Pokemon Red View System we've built, and make the system game-agnostic where we can, with pre-sets based on the game/type?"

Measured root cause of the mismatch (read from the code, not assumed):

- The Gameplay window is `tools/mario_display.py`: one live emulator that replays the best run found so far (`play_best`, from `mario_search.read_best`). It publishes one card, `AGENT = "mario-land"`.
- The Map view (`src/pokeagent/mapview/`, PR #172) draws the recorded ghost files `<source>/ghosts/<run>.json` (up to 60, written by `tools/mario_maps.py`) on its own replay clock and follows the furthest ghost (`mapview/best.py`). Those are different attempts at different times, so the two windows can never agree.
- Nothing tells the Map view where the live emulator is right now. That is the missing contract.
- `mapview/overlay.py` draws every agent as a coloured square ("head"). `world/draw.py` draws Pokemon agents as the game's own player sprite (`SpriteBook`, `draw_agent`, with facing and walk phase from `world/anim.py`), tinted per agent. The Map view has no equivalent, and no way to say "this is a platformer, that is an overworld RPG".

**Base requirement:** this run must start from a main that contains PR #171 (`tools/mario_display.py`, `tools/mario_search.py`, `tools/mario_maps.py`) and PR #172 (`src/pokeagent/mapview/`, `tools/map_view.py`). Check with `git grep -n "def positions" -- src/pokeagent/mapview/playback.py` and `git grep -n "class Display" -- tools/mario_display.py`. If either finds nothing, stop and write that in the Status row; do not recreate those files.

Facts about the existing code, pasted because the worktree cannot be searched for them reliably:

- `mapview/` files and their limits from PR #172: `view.py` 279 of 280 lines (it is AT its limit, so it must not grow; see the work), `app.py` 125 of 150, `overlay.py` 109 of 200, `playback.py` 100 of 200. Ghost heads are drawn in `overlay.render(frame, ghost_tables, layout, rect, zoom, palette)` as filled squares into ONE RGBA array the size of the visible rectangle; there are no per-ghost Dear PyGui items and that stays true.
- `mapview/app.py` has `Snapshot` (immutable: areas, layout, ghost tables), `Holder` (lock-guarded get/set), `snapshot_once(...)` and `poll_loop(...)` on a daemon thread every `REFRESH_S = 2.0`. The UI thread only reads the Holder.
- The vocabulary rule of #172: `src/pokeagent/mapview/` contains no game words (`mario`, `pokemon`, `kanto`, `lives`, `score`, `map_id`, `level`), enforced by `tests/test_mapview_vocabulary.py`. This directive allows exactly ONE exemption: the file `src/pokeagent/mapview/presets.py` (a data table that names games). Every other file stays clean, and the test is changed to exempt only that file.
- Pokemon avatar path, for reference only: `world/draw.py` `SpriteBook(rom).image(sprite_id, facing, phase, colour)` returns a tinted RGBA PIL image; `atlas/sprites.py` `PLAYER = 1`, `pick_frame(frames, facing, walk_phase)` and `sprite_rgba(img, outline)`. These need ROM bytes. A Devin worktree has no ROM, so the `rom_sprite` source is built against an injected provider and tested with a fake provider.

Read first: `src/pokeagent/mapview/overlay.py`, `mapview/app.py`, `mapview/view.py`, `world/anim.py`, `tools/mario_display.py` (`Display.watch`, `Display.refresh`), `tools/mario_maps.py` (how it names runs and maps a position to `[area, x, y]`; the live file MUST use the same area names and the same x/y convention as the ghost points), `tests/test_mapview_vocabulary.py`. The #172 tests that must stay green, present once #172 is on main: `tests/test_mapview_areas.py`, `tests/test_mapview_layout.py`, `tests/test_mapview_ghosts.py`, `tests/test_mapview_playback.py`, `tests/test_mapview_overlay.py`, `tests/test_mapview_best.py`, `tests/test_mapview_window.py`.

## Scope (in this order)

1. `src/pokeagent/mapview/live.py` <!-- new: src/pokeagent/mapview/live.py --> - the live position contract: atomic writer, tolerant reader, `LiveStore`. Under 130 lines.
2. `src/pokeagent/mapview/presets.py` <!-- new: src/pokeagent/mapview/presets.py --> - the view preset registry, a plain data table plus `resolve`. Under 120 lines. The only mapview file allowed to name games.
2b. `src/pokeagent/mapview/edges.py` <!-- new: src/pokeagent/mapview/edges.py --> - edge colours and edge lines for stacked areas. Pure numpy. Under 90 lines.
3. `src/pokeagent/mapview/avatars.py` <!-- new: src/pokeagent/mapview/avatars.py --> - `frame_crop` avatars: crop, key out background, tint, in-memory cache. Pure numpy. Under 150 lines.
4. `src/pokeagent/mapview/avatar_rom.py` <!-- new: src/pokeagent/mapview/avatar_rom.py --> - the `rom_sprite` source as an adapter over an injected sprite provider. Under 70 lines.
5. `src/pokeagent/mapview/walk.py` <!-- new: src/pokeagent/mapview/walk.py --> - facing and walk phase from position change. Pure. Under 70 lines.
6. `src/pokeagent/mapview/overlay.py` - draw avatars where heads were (edit). Stays under 200 lines.
7. `src/pokeagent/mapview/app.py` - read `live/` in the refresh thread, add live agents and the preset to `Snapshot`, accept `--game` / `--preset` (edit). Stays under 150 lines.
8. `src/pokeagent/mapview/view.py` - use the preset and the live agent; Follow live (edit). MUST NOT exceed 280 lines: if the change needs lines, first extract existing code into a new `src/pokeagent/mapview/controls.py` <!-- new: src/pokeagent/mapview/controls.py --> with no behaviour change (existing window tests stay green), then add. `controls.py` under 120 lines.
9. `tools/mario_live.py` <!-- new: tools/mario_live.py --> - the Mario side of the contract: build and throttle the live record from the emulator. Under 90 lines.
10. `tools/mario_display.py` - call the throttled live writer from the existing `watch` loop (edit, a few lines only).
11. `tests/test_mapview_vocabulary.py` - exempt `presets.py` only (edit).
12. Tests, all new: <!-- new: tests/test_mapview_live.py --> <!-- new: tests/test_mapview_presets.py --> <!-- new: tests/test_mapview_avatars.py --> <!-- new: tests/test_mapview_avatar_rom.py --> <!-- new: tests/test_mapview_walk.py --> <!-- new: tests/test_mapview_edges.py --> <!-- new: tests/test_mapview_overlay_avatars.py --> <!-- new: tests/test_mario_live.py -->. Edited, existing from PR #172: `tests/test_mapview_window.py`, `tests/test_mapview_vocabulary.py`.
13. `docs/KNOWLEDGE.md` - a short paragraph: live file schema, presets, avatar sources.

## The work

### live.py: the live position contract (generic words only)

File: `<source>/live/<agent>.json`, one per displayed agent, written atomically (write `<agent>.json.tmp` in the same directory then `os.replace`), about 10 Hz:

```
{"schema": 1, "agent": "mario-land", "run": "1731030000123-2", "area": "1-1", "x": 412, "y": 88, "screen_x": 72, "screen_y": 96, "updated_at": 1731030001.25}
```

- `x`, `y` use exactly the ghost-point convention (`points` entries are `[area, x, y]`), so the live agent lands on the same stitched map as the ghosts. `screen_x`, `screen_y` are the agent's sprite position in its own live frame, in frame pixels (top-left of the sprite's box), or `null` when unknown. `run` is the id of the recorded attempt the live display is replaying (so the viewer can tell which ghost it is the live copy of), or `""` when unknown. `updated_at` is epoch seconds.
- `write_live(source: Path, record: dict) -> None` validates keys and types, writes atomically, creates `live/` if missing, never raises on I/O errors (returns quietly; the caller must not die because a viewer file failed).
- `read_live(path) -> LivePos | None`: tolerant like `load_ghost`: `None` for unreadable, invalid JSON, wrong schema, missing keys, non-finite numbers. Never raises.
- `@dataclass(frozen=True) class LivePos: agent, run, area, x, y, screen_x: int | None, screen_y: int | None, updated_at`.
- `LiveStore.refresh(source, now) -> bool`: lists `live/*.json`, re-parses only changed files (mtime and size), forgets vanished ones, treats a record older than `STALE_S = 5.0` as absent (a stopped display must not leave a frozen avatar). Returns True on change. `positions()` returns `dict[agent, LivePos]`.
- Writer throttle lives in the caller (`tools/mario_live.py`), not here.

### presets.py: the view preset registry (plain data)

- A frozen dataclass `Preset` with fields: `name`, `genre`, `layout` (`"strip"` for platformer and flip-screen areas laid out in rows as `layout.place` does today, `"grid"` for rpg-overworld), `avatar` (`"frame_crop"` or `"rom_sprite"`), `avatar_size` (px at zoom 1), `trail` (`"line"` or `"dots"`), `trail_points` (int), `follow_default` (`"live"` or `"best"`), `status_fields` (tuple of snapshot field names the host shows), `walk_frames` (bool: the preset provides frames, so facing and phase apply).
- `GENRES` table: `platformer`, `rpg-overworld`, `flip-screen`, each a full `Preset` with sensible defaults (platformer: strip, frame_crop, side-on facing, trail line; rpg-overworld: grid, rom_sprite, walk_frames True, trail dots; flip-screen: strip, frame_crop).
- `GAMES` table: `super-mario-land` (inherits `platformer`) and `pokemon-red` (inherits `rpg-overworld`), each given as `{"inherits": "<genre>", **overrides}`; `resolve` applies the override over the genre with `dataclasses.replace`. Status fields for Super Mario Land: `("segment", "progress", "box_text")`; for Pokemon Red: `("segment", "party", "money")`. Use only fields that exist on `AgentSnapshot` today; if a field name is not on `AgentSnapshot`, drop it and record the gap in the Report as a decision.
- `resolve(game: str | None = None, preset: str | None = None, genre: str | None = None) -> Preset`: order of precedence `preset` name, then `game`, then `genre`, then `DEFAULT_GENRE = "platformer"`. An unknown name does not raise: it falls back to the genre default of the closest known genre (unknown game with a known genre uses that genre, otherwise `DEFAULT_GENRE`) and `Preset.name` says `"<requested>?"` so the window can show "unknown preset". Pure, no I/O.
- Stacked areas with edge lines (Robert, 2026-11-08: "doing the stacked maps the way you're doing, just with a tiny boundary space between them, works perfect as the mario world view. Maybe 5-10px Edge Lines between each map, different colors, to make them easier to distinguish"). Two more `Preset` fields: `area_gap_px: int` (world pixels between stacked areas; `platformer` and `flip-screen` default 8; the value is clamped to 5..10 by `resolve`, so a table typo cannot produce a 40 px gap) and `edge_palette: tuple[str, ...]` (hex colours such as `"#e6194b"`, at least 4 distinct ones, defined in the table). `rpg-overworld` sets `area_gap_px` to 0 and an empty palette (no edges; the Kanto renderer ignores them).
- This is a plain data table: no behaviour in the table values, so it can later be absorbed into the `GameSpec` of the Multi_Game_Framework plan unchanged. Say so in the module docstring.

### edges.py and layout: tiny gap, coloured edge lines in the static base

- The stacked-areas layout of #172 (`layout.place`, areas in rows) is kept. `app.py` passes `preset.area_gap_px` as `gap` to `layout.place`. Every offset, `layout.locate` result, ghost position, live position and click hit test already goes through the layout offsets, so the gap is accounted for with no second code path; the test below proves it.
- `edge_colours(areas_layout, palette) -> dict[str, str]`: one colour per area, cycling the palette in index order, then fixed up so that no area shares a colour with the previous or next area in index order, nor with the area directly above or below it in the layout (compare offsets: same column span overlap, adjacent row). With a palette shorter than the area count it still keeps neighbours distinct by choosing the next palette colour that differs from every neighbour; with a palette of fewer than 3 distinct colours it may repeat but never between index neighbours. Pure, deterministic.
- `draw_edges(base: np.ndarray, layout, colours: dict[str, str], width: int = 2) -> None`: draws a rectangle outline of `width` px in the area's colour around each area image inside the gap (outside the image bounds, so the map pixels are untouched), clipped to the base. Drawn into the static base image ONCE when the base is rebuilt (`mapview/compose.py` calls it; edit that file by a few lines), never per frame, so per-frame cost and the overlay are unchanged. With `area_gap_px` of 0 nothing is drawn.

### avatars.py: `frame_crop`

- `crop_avatar(frame: np.ndarray, sx: int, sy: int, size: int, key: tuple[int, int, int] | None = None) -> np.ndarray | None`: crop a `size` x `size` box at (`sx`, `sy`) from the live RGB frame (clip to the frame; return `None` when fully outside), then key out the background: the background colour is `key` when given, otherwise the most common colour in a 1-pixel ring around the box, and every pixel within `KEY_TOL = 24` per channel of it becomes transparent. Returns an (h, w, 4) uint8 array. If the crop is more than 90 percent transparent or 0 percent transparent (nothing keyed), return `None` (a bad crop is worse than a dot).
- `tint(rgba, colour) -> np.ndarray`: blend a per-agent colour into the opaque pixels (mix about 35 percent, keep alpha) plus a 1 px outline in the agent colour so tinted ghosts of one game stay readable at a glance.
- `class AvatarCache`: holds the best crop per game in memory only (a dict keyed by preset name and facing), `offer(preset, facing, frame, live: LivePos) -> None` (replaces the held crop only when the new one is "better": more opaque pixels without exceeding `size`), `get(preset, facing, colour) -> np.ndarray | None`, a tinted-variant cache keyed by `(preset, facing, colour)`. Returns `None` until the first good crop exists; the overlay then draws a dot. Crops are NEVER written to disk: no `np.save`, no `Image.save`, no files; the test patches `open`, `Path.write_bytes` and `PIL.Image.Image.save` to raise and offers a crop.
- Every ghost of the game uses the same crop, tinted by the ghost's agent colour: the crop is the game's player picture, not a per-agent photo.

### avatar_rom.py: `rom_sprite`

- `class RomAvatars`: constructed with a provider callable `provider(facing: str, phase: int, colour: tuple[int,int,int]) -> np.ndarray | None` (RGBA). `get(facing, phase, colour)` returns the provider result or `None` on any `ValueError`/`IndexError`/`KeyError` from it. It does not import `world.draw` at module level. A second function `book_provider(rom_bytes)` builds a provider from `pokeagent.world.draw.SpriteBook` (`book.image(atlas.sprites.PLAYER, facing, phase, colour)` converted with `np.asarray`) with the import INSIDE the function. Nothing here is called unless the preset's avatar is `rom_sprite` AND the caller supplies bytes; tests pass a fake provider. Pokemon behaviour is untouched (nothing in `world/` or `viewer/` calls this yet).

### walk.py

- `facing_from(prev: tuple[float,float] | None, cur: tuple[float,float], walk_frames: bool, last: str = "DOWN") -> str`: for a position change, `"RIGHT"`/`"LEFT"` when |dx| >= |dy| else `"DOWN"`/`"UP"`; no change keeps `last`; for a platformer-style preset (`walk_frames` False) only `"LEFT"`/`"RIGHT"` are produced and a pure vertical change keeps `last`.
- `phase_from(index: int, moved: bool, walk_frames: bool) -> int`: 0 when not moved or the preset has no frames, else 1 or 2 alternating every 6 steps (`index // 6 % 2 + 1`).
- Both pure; used by the overlay for ghosts (from consecutive points) and for the live agent (from consecutive reads).

### overlay.py, app.py, view.py

- `overlay.render` gains an optional `avatars` argument (a small object with `get(agent, facing, phase, colour) -> RGBA | None`) and the preset's `avatar_size`. For each visible head: if an avatar exists, alpha-composite it centred on the head position scaled by zoom (nearest neighbour, via numpy index repeat; no per-ghost Dear PyGui items; still ONE RGBA array); otherwise draw the existing square. The live agent is drawn the same way, plus a 1 px white ring so the player can tell "the live one" from ghosts. The best ghost keeps its white outline. Cost must still not scale per ghost beyond a small constant: composite only the ghosts inside the rectangle, and the existing ratio test (60 vs 5 ghosts under 3 times) stays green.
- `app.py`: `Snapshot` gains `live: dict[str, LivePos]` and `preset: Preset`. `snapshot_once` calls `LiveStore.refresh`. New arguments `--game NAME` and `--preset NAME` (preset wins), and `--genre NAME`; the window falls back to the genre default when none is given. The refresh thread also feeds the `AvatarCache`: each cycle, if the host provides a latest live frame for the live agent, offer the crop. In the standalone Map view there is no frame source, so `AvatarCache` is fed by an optional callable `frame_for(agent) -> (rgb_bytes, w, h) | None` that the standalone launcher leaves as `None` (the avatar then stays a dot there; directive 2 passes the viewer's frame source). Say this in the Report: the standalone window cannot make crops by itself.
- `view.py`: `Follow live` replaces `Follow best` as the default whenever `preset.follow_default == "live"` and a live agent exists in the snapshot (camera follows the live agent's space position through `layout.locate`; falls back to best ghost when no live agent). Pan still disables follow (already done in #172). The status line shows `preset.status_fields` values when the host provides them, else nothing. Show "unknown preset" when `Preset.name` ends with `?`.

### mario_live.py and mario_display.py

- `tools/mario_live.py`: `class LiveWriter(source: Path, agent: str, hz: float = 10.0)` with `maybe_write(state: dict, now: float) -> None`: writes through `pokeagent.mapview.live.write_live` no more than `hz` times per second (monotonic time passed in, no sleeping). `build_record(display) -> dict | None` assembles the record from the live `Display`: `area` and `x`, `y` from the SAME function `tools/mario_maps.py` uses to turn the emulator state into `[area, x, y]` (import it from `mario_maps`; do not duplicate the maths; if it is not importable as a function, extract it into a tiny shared function inside `mario_maps.py` without changing its output and say so), `run` is the id `mario_maps.py` gives the ghost of the sequence being replayed when that is derivable from the best doc, else `""` (record this as a decision in the Report), and `screen_x`/`screen_y` come from `locate_player(sprites)` below.
- `locate_player(sprites, tile_ids) -> tuple[int,int] | None`: pure; `sprites` is a list of `(x, y, tile_id)` tuples read from the emulator's sprite table by the caller, `tile_ids` is the set of tile ids that make up the player; returns the top-left of the bounding box of the matching sprites, or `None` when none match. Define `PLAYER_TILE_IDS: frozenset[int] = frozenset()` in this module, EMPTY, with the comment "filled in by the real-window check; see Required from User". Do not guess tile ids. While it is empty `screen_x`/`screen_y` are `null` and the viewer shows a dot: that is the designed fallback, not a bug.
- `tools/mario_display.py`: in `Display.__init__` create the `LiveWriter` for the same source directory `mario_maps.py` writes to (use the constant that file uses; read it in the worktree); in `Display.watch` call `maybe_write(...)` after the existing publish. A failure inside it is caught and ignored (a broken viewer file must never stop the emulator). Change nothing else in that file.

## What NOT to do

- Do not change anything under `src/pokeagent/world/` or `src/pokeagent/atlas/` (no edit, no rename, no new file). Pokemon Red behaviour stays byte-identical: `git diff --stat main -- src/pokeagent/world src/pokeagent/atlas src/pokeagent/viewer` must be empty.
- Do not edit `src/pokeagent/viewer/` or `tools/watch_game.py`: the unified viewer is directive 2's work.
- Do not add game words to any `mapview/` file except `presets.py`. Do not hard-code a game name in `overlay.py`, `avatars.py`, `walk.py` or `live.py`: they read the `Preset` fields.
- Do not persist extracted art: no crop, tile, sprite sheet or tinted variant written to disk, cache directory, log or test fixture. Memory only.
- Do not guess the Mario player tile ids, and do not read or open any ROM; a worktree has none.
- Do not read, print or state where any game copy came from, in code, comments, docs or the report.
- Do not touch `roms/`, `baselines/`, any ROM data, or any other Mario file than the two named in Scope.
- Do not add a dependency; numpy, Pillow and Dear PyGui are installed.
- No per-agent Dear PyGui items; one overlay texture stays the contract.
- No scratch or debug files outside `.devin-scratch/`; deleting is denied in the sandbox.
- A test never creates a viewport, never sends input, never opens a window.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_mapview_live.py tests/test_mapview_presets.py tests/test_mapview_avatars.py tests/test_mapview_avatar_rom.py tests/test_mapview_walk.py tests/test_mapview_edges.py tests/test_mapview_overlay_avatars.py tests/test_mario_live.py tests/test_mapview_vocabulary.py
```
Expected: all pass.

```
uv run pytest -q tests/test_mapview_areas.py tests/test_mapview_layout.py tests/test_mapview_ghosts.py tests/test_mapview_playback.py tests/test_mapview_overlay.py tests/test_mapview_best.py tests/test_mapview_window.py
```
Expected: the #172 tests still pass unchanged (the window tests may gain assertions, none may be weakened).

```
uv run pytest -q tests/test_world_view.py tests/test_world_follow.py tests/test_viewer_tiles_world.py
```
Expected: same result as on main.

```
git diff --stat main -- src/pokeagent/world src/pokeagent/atlas src/pokeagent/viewer
```
Expected: no output.

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Tests are headless: `dpg.create_context()` and `dpg.destroy_context()` at most. No `create_viewport`, no `show_viewport`, no `setup_dearpygui`, no input events, nothing may open a window on Robert's screen.
- Fixtures are synthetic and made inside the test with `tmp_path` or numpy: a 160x144 frame with a flat background and a small coloured sprite box at a known position; live JSON files; fake sprite providers. No ROM, no committed fixture, nothing read from `runs/`.
- Branch only (`directive/pokeagent-game-view-presets-and-avatars-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Done for the Status row means `Review`, with the diff stat, test tails, new-file line counts and every decision made where this directive was silent, in the Report.

## Completion criteria

- [ ] `write_live` writes the schema-1 record atomically (no `.tmp` left behind, `live/` created); `read_live` returns a `LivePos` for it and `None` (no raise) for truncated JSON, wrong schema, missing keys, non-finite numbers; `LiveStore.refresh` picks up a new file, drops a deleted one, re-parses only a changed one (assert the parse count), and treats a record older than `STALE_S` as absent; a failing write (read-only directory simulated by patching `os.replace` to raise) does not raise. <!-- test: tests/test_mapview_live.py -->
- [ ] `edge_colours` gives different colours to index neighbours and to vertical neighbours in a fixed layout; with more areas than palette colours (for example 9 areas, 4 colours) neighbours are still distinct; `resolve` clamps `area_gap_px` to 5..10 (a table value of 40 comes back 10, of 1 comes back 5) while 0 is kept for `rpg-overworld`; `layout.place` called with the preset gap puts the second area exactly `gap` px (plus label height) after the first in the same row, `locate` returns positions shifted by that offset, and `draw_edges` colours pixels only inside the gap ring (area pixels unchanged, asserted on a synthetic base) and draws nothing for gap 0. <!-- test: tests/test_mapview_edges.py -->
- [ ] `resolve` returns the genre default for each of `platformer`, `rpg-overworld`, `flip-screen`; `super-mario-land` inherits `platformer` with its overrides and `pokemon-red` inherits `rpg-overworld`; precedence is preset, game, genre, `DEFAULT_GENRE`; an unknown name falls back without raising and its `name` ends with `?`; the tables are plain data (a test asserts every value is a str, int, bool or tuple of str). <!-- test: tests/test_mapview_presets.py -->
- [ ] `crop_avatar` cuts the known sprite box out of a synthetic frame with the background transparent, returns `None` when fully outside the frame, when nothing is keyed, and when over 90 percent is keyed; `tint` changes opaque pixels only and keeps alpha; `AvatarCache.get` is `None` before the first `offer`, then returns a crop for any colour, a better crop replaces a worse one, and the same tinted array is returned from cache on a second call; nothing is written to disk (patched `open`, `Path.write_bytes` and `PIL.Image.Image.save` raise and the test still passes). <!-- test: tests/test_mapview_avatars.py -->
- [ ] `RomAvatars.get` returns the fake provider's array, returns `None` when the provider raises `ValueError`, `IndexError` or `KeyError`, and importing `pokeagent.mapview.avatar_rom` does not import `pokeagent.world.draw` (assert via `sys.modules` in a fresh subprocess-free check using `importlib` after removing the key). <!-- test: tests/test_mapview_avatar_rom.py -->
- [ ] `facing_from` and `phase_from` give the specified results for all four directions, no change, a platformer preset (`walk_frames` False: left/right only, vertical keeps last) and the alternation every 6 steps. <!-- test: tests/test_mapview_walk.py -->
- [ ] `render` with an avatar cache draws the avatar pixels (not the square) at the expected position for a ghost and for the live agent (white ring present only for the live one); with an empty cache it draws the square as before; the array is still exactly the visible rectangle; the 60-versus-5-ghost cost ratio stays under 3; a ghost outside the rectangle draws nothing. <!-- test: tests/test_mapview_overlay_avatars.py -->
- [ ] `build_record` and `LiveWriter` produce the schema-1 record from a fake display object, write no more than 10 times per second for calls at 100 Hz (injected clock), produce `screen_x`/`screen_y` of `null` while `PLAYER_TILE_IDS` is empty, and `locate_player` returns the bounding box top-left for matching tile ids and `None` for none. <!-- test: tests/test_mario_live.py -->
- [ ] The window builds headless with a preset and a live agent: the live agent is in the overlay, `Follow live` moves the Viewport centre toward the live position, falls back to the best ghost when no live file exists, and an unknown preset shows the "unknown preset" text; refresh with a new live file changes the next snapshot without moving the camera when follow is off. <!-- test: tests/test_mapview_window.py -->
- [ ] `src/pokeagent/mapview/` contains none of the banned words except in `presets.py`; every file is under its stated line limit (`view.py` still at most 280). <!-- test: tests/test_mapview_vocabulary.py -->
- [ ] `git diff --stat main -- src/pokeagent/world src/pokeagent/atlas src/pokeagent/viewer` is empty and the existing world and viewer tests pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat; test tails; line count of each new file against its limit; decisions made where this directive was silent (the `run` tag source, the edge line width, any status field dropped from a preset, any `mario_maps.py` function extraction); the constants chosen (`STALE_S`, `KEY_TOL`, live write rate); and the real-window checklist below.

Real-window checklist (Claude, in a real window; Devin cannot do it): (1) with the Mario display running, find the player's tile ids from the OAM sprite table of the live emulator and fill `PLAYER_TILE_IDS` in `tools/mario_live.py` (a one-line change after the real-window check); (2) `uv run python tools/map_view.py runs/mario-land --game super-mario-land` shows a Mario-shaped avatar at the live position, not a dot, and the same picture tinted on every ghost; (3) the live avatar is on the same spot the Gameplay window shows (same area, within a few pixels); (4) the avatar faces the direction it moves; (5) the stacked areas show a thin gap with a differently coloured edge line around each map, easy to tell apart; (5b) stopping the display removes the live avatar within about 5 seconds; (6) a ghost count of 60 keeps the frame rate flat.

## Forbidden Actions

- Do not touch `roms/`, `baselines/` or any ROM data, do not persist extracted art, and do not state where a game copy came from.
- Do not edit anything under `src/pokeagent/world/`, `src/pokeagent/atlas/`, `src/pokeagent/viewer/`, `src/pokeagent/cli.py`, `src/pokeagent/emulator.py`, or any Mario file under `tools/` other than `tools/mario_display.py`, `tools/mario_live.py` and the single-function extraction allowed in `tools/mario_maps.py`.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a Dear PyGui viewport, send input, or open any window in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The real-window checklist above, after the Claude verify lane passes. Robert runs nothing; Claude does the player tile ids and the visual check. Nothing here blocks the run.
- PRs #171 and #172 merged to main before dispatch (or the run branched from a base that contains both).

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
- 2026-11-08 13:34 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert: live position contract, view presets, avatars; needs PRs 171 and 172 on main
- 2026-11-08 13:35 · robert-claude-laptop · Queued → Draft — Back to Draft to add area gap and edge lines requirement from Robert; will requeue
- 2026-11-08 13:36 · robert-claude-laptop · Draft → Queued — Requeued with area gap and edge lines requirement
<!-- queue:end -->
