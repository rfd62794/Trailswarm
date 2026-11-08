# PokeAgent: Vision label recorder - play a game headless and write a local dataset of sprite and tile crops labelled for free from RAM and OAM

## Why this exists

Robert, 2026-11-08, approved: use game RAM as free labels to train cheap local models. Every frame the emulator renders has an exact answer in memory (which sprite, where, on which map), so a recorder can produce labelled pixels with no human labelling. This directive is the data source; directive 2 (`Cheap_Sprite_Model_Directive.md`) trains a sprite classifier on it and directive 3 (`Movement_And_Location_Models_Directive.md`) trains movement and location models on it. Neither can start until this one is merged.

What exists today (read, not guessed):

- `src/pokeagent/emulator.py` is the only file that imports PyBoy. The `Emulator` protocol gives `read`, `read_range`, `tick_rendered(frames)`, `frame_rgb()` (144x160x3 RGB bytes, valid right after a rendered tick), `load_state`, `press`. `PyBoyEmulator(rom_path, headless=True)` opens no window. `FakeEmulator` is an in-memory fake whose `read_range` returns 0 for unset bytes and whose `frame_rgb()` is all zeros. This directive does NOT edit `emulator.py`: OAM and VRAM are plain addresses and `read_range` reaches them.
- Pokemon Red NPC data is already read in two places: `src/pokeagent/explorer/anomaly_sprites.py` (`read_sprites`) and `MapMemory.observe_npcs` in `src/pokeagent/explorer/memory.py`. The sprite table is `wSpriteStateData1` at 0xC100 and `wSpriteStateData2` at 0xC200, 16 bytes per slot, slot 0 is the player, slots 1 to 15 are NPCs. Pasted:

```
SPRITE_STATE1 = 0xC100   # +0 picture id (0 = empty slot), +2 image index (0xFF = hidden)
SPRITE_STATE2 = 0xC200   # +4 map y + 4, +5 map x + 4, +6 movement byte (believed: 0xFF stay, 0xFE walk; UNVERIFIED, record raw)
slot i, map x = read(0xC205 + 16*i) - 4 ; map y = read(0xC204 + 16*i) - 4
BALL_PIC = 61            # pick-up ball picture id (src/pokeagent/atlas/overlay.py)
```
- Pokemon Red RAM map (`src/pokeagent/ram.py` `RAM_MAP`): `map_id` 0xD35E, `player_y` 0xD361, `player_x` 0xD362, `in_battle` 0xD057. The tileset id byte is believed to be `wCurMapTileset` at 0xD367 (UNVERIFIED: record it, and Claude checks it with the ROM).
- Super Mario Land (the repo reads it in `tools/mario_maps.py`, which this run must not edit): world-level byte at 0xFFB4 (high nibble world, low nibble level), Mario screen x at 0xC202, Mario y at 0xC201 (the game's sprite y is 16 below the screen top), level block at 0xC0AB, `level_progress = block * 16 + (SCX - 7) % 16 + mario_x`, lives at 0xDA15 (BCD). The HUD is the top 16 screen pixels.
- Game Boy hardware addresses, which hold for any GB game: OAM 0xFE00, 40 entries of 4 bytes `(y, x, tile, attr)` where screen y = byte0 - 16 and screen x = byte1 - 8; LCDC 0xFF40 (bit 2 = sprites are 8x16, bit 3 = background map select: 0 -> 0x9800, 1 -> 0x9C00); SCY 0xFF42, SCX 0xFF43; background map is 32x32 tile ids, row major; the visible 160x144 window starts at (SCX, SCY) and wraps at 256. PyBoy's own `Sprite` class (`pyboy/api/sprite.py`) computes exactly this, it is the cross-check, but this repo must read it through the `Emulator` protocol so it stays PyBoy-free and fake-testable.
- `src/pokeagent/ramlab/replay.py` and `headless.py` show headless driving: tick 60, `load_state`, tick 30, then presses. `tools/mario_maps.py` shows the Mario replay (reads PyBoy directly because it predates the seam).

Dataset contract (directives 2 and 3 import `pokeagent.vision.dataset`, which this run writes; keep these names exact):

```
runs/vision/<game>/                      game is "pokemon-red" or "mario-land"; the whole tree is gitignored
  meta.json         {"schema":1,"game","created","sample_every","frames_seen","bytes","caps":{...},"label_source":"<name>"}
  images/<hh>/<sha1>.png   unique crops, <hh> = first two hex chars, sha1 of (width, height, raw RGB bytes)
  samples.jsonl     one JSON object per UNIQUE (kind, label, area, image) with a count, written atomically at the end and every 60 s:
     {"id":"<sha1>","kind":"sprite"|"tile","label":<int>,"coarse":"enemy"|"npc"|"item"|"player"|"terrain"|"other",
      "area":"<string>","region":"r<0-2>c<0-2>","x":<int>,"y":<int>,"w":<int>,"h":<int>,"count":<int>,"bank":<int|null>}
  thumbs/<hh>/<sha1>.png   80x72 greyscale thumbnails of whole frames (160x144 halved), deduplicated
  thumbs.jsonl      {"id","area","cell":"<string>","pos":[x,y],"count"}   one line per unique (area, cell, image)
  positions.jsonl   one line per sampled frame: {"f":<frame>,"run":"<run id>","area","player":[x,y],"ents":[[ident,label,x,y,move],...]}
```
`label` for Red sprites is the picture id, for Mario sprites the OAM tile id, for tiles the background tile id; `bank` is the Red tileset id for tiles (a tile id means different art in different tilesets) and null otherwise. `area` is `map-<id>` for Red and `<world>-<level>` for Mario. `region` is the 3x3 screen cell holding the box centre. `ident` is `slot<i>` for Red NPCs (stable within a run) and `oam<i>` for Mario (NOT stable across frames; directive 3 uses Red only). `move` is the raw movement byte for Red, null for Mario. Positions for Red are map tile coordinates; for Mario they are screen pixels plus `level_progress` in `player`.

## Scope (in this order)

1. `src/pokeagent/vision/__init__.py` <!-- new: src/pokeagent/vision/__init__.py --> - one-line docstring.
2. `src/pokeagent/vision/labels.py` <!-- new: src/pokeagent/vision/labels.py --> - frozen dataclasses `SpriteBox(label, coarse, x, y, w, h, ident, move)`, `TileCell(label, x, y)`, `FrameLabels(area, bank, player, cell, sprites, tiles, skip)`, and the `LabelSource` Protocol. Under 80 lines.
3. `src/pokeagent/vision/oam.py` <!-- new: src/pokeagent/vision/oam.py --> - parse 160 OAM bytes plus the LCDC byte into on-screen boxes. Pure. Under 70 lines.
4. `src/pokeagent/vision/bgmap.py` <!-- new: src/pokeagent/vision/bgmap.py --> - the 20x18 visible background tile cells from the 1024-byte map, SCX, SCY and the LCDC map bit. Pure. Under 60 lines.
5. `src/pokeagent/vision/source_red.py` <!-- new: src/pokeagent/vision/source_red.py --> - the Pokemon Red label source. Under 120 lines.
6. `src/pokeagent/vision/source_mario.py` <!-- new: src/pokeagent/vision/source_mario.py --> - the Super Mario Land label source. Under 120 lines.
7. `src/pokeagent/vision/sources.py` <!-- new: src/pokeagent/vision/sources.py --> - `SOURCES: dict[str, LabelSource]` registry and `get_source(game)`. Under 40 lines.
8. `src/pokeagent/vision/crops.py` <!-- new: src/pokeagent/vision/crops.py --> - cut a box out of a frame, content hash, thumbnail. Pure numpy and Pillow. Under 80 lines.
9. `src/pokeagent/vision/store.py` <!-- new: src/pokeagent/vision/store.py --> - deduplicating writer with the size caps and the atomic index writes. Under 180 lines.
10. `src/pokeagent/vision/positions.py` <!-- new: src/pokeagent/vision/positions.py --> - the per-frame position log writer with its own size cap. Under 80 lines.
11. `src/pokeagent/vision/driver.py` <!-- new: src/pokeagent/vision/driver.py --> - where the presses come from: a script file, or a seeded random walk. Under 120 lines.
12. `src/pokeagent/vision/record.py` <!-- new: src/pokeagent/vision/record.py --> - `record(emu, source, store, positions, driver, ...)`: the loop, taking an `Emulator` so a fake can drive it. Under 140 lines.
13. `src/pokeagent/vision/dataset.py` <!-- new: src/pokeagent/vision/dataset.py --> - the reader directives 2 and 3 import: `load_meta`, `iter_samples(root)`, `load_image(root, id)`, `iter_thumbs(root)`, `load_thumb(root, id)` (an `(72, 80)` uint8 greyscale array), `iter_positions(root)`. Tolerant of a half-written last line. Under 120 lines.
14. `tools/vision_record.py` <!-- new: tools/vision_record.py --> - a thin launcher with argument parsing and the real `PyBoyEmulator`. Under 120 lines.
15. `.gitignore` - add the legal entries (see the work).
16. `docs/KNOWLEDGE.md` - a short "Vision dataset" paragraph: what is written, where, that it is local only.
17. Tests under `tests/`, listed in the completion criteria: `tests/test_vision_oam.py`, `tests/test_vision_bgmap.py`, `tests/test_vision_sources.py`, `tests/test_vision_store.py`, `tests/test_vision_positions.py`, `tests/test_vision_driver.py`, `tests/test_vision_record.py`, `tests/test_vision_dataset.py`, `tests/test_vision_legal.py`. <!-- new: tests/test_vision_oam.py --> <!-- new: tests/test_vision_bgmap.py --> <!-- new: tests/test_vision_sources.py --> <!-- new: tests/test_vision_store.py --> <!-- new: tests/test_vision_positions.py --> <!-- new: tests/test_vision_driver.py --> <!-- new: tests/test_vision_record.py --> <!-- new: tests/test_vision_dataset.py --> <!-- new: tests/test_vision_legal.py -->

Do not edit `src/pokeagent/emulator.py`, `src/pokeagent/cli.py` or anything under `src/pokeagent/explorer/`.

## The work

### Label source (the per-game seam)

```python
class LabelSource(Protocol):
    name: str                      # "pokemon-red"
    boot_presses: tuple            # (button name, hold, settle) presses to reach play from a cold boot, may be empty
    def read(self, emu) -> FrameLabels: ...
```
`read` is called after a rendered tick and returns everything for that frame in one pass: the `area` string, the Red `bank` (tileset id) or None, `player` (Red `(x, y)` map tile; Mario `(level_progress, y)`), `cell` (a coarse position bucket string: Red `f"{x//4},{y//4}"`, Mario `f"{progress//128}"`), the sprite boxes, the background tile cells, and `skip` (True when this frame must not be recorded). Adding a game means adding one source module and one line in `sources.py`; `record.py` has no game terms.

### oam.py

`on_screen_boxes(oam: bytes, lcdc: int) -> list[tuple[int, int, int, int, int]]` returns `(index, tile, x, y, h)` for every entry that is on screen, where height is 16 when LCDC bit 2 is set and 8 otherwise, width is always 8, `y = byte0 - 16`, `x = byte1 - 8`, and an entry counts as on screen when `-h < y < 144` and `-8 < x < 160` (the same test as PyBoy `Sprite.on_screen`). Clip boxes to the screen when cropping, never index outside the frame. For a 16-high entry the tile id used as the label is `tile & 0xFE` (hardware ignores bit 0 there).

### bgmap.py

`visible_cells(bg_map: bytes, scx: int, scy: int, skip_top_px: int = 0) -> list[TileCell]`: the 20x18 cells of the visible window, cell `(cx, cy)` has pixel position `(cx*8 - scx % 8, cy*8 - scy % 8)` and tile id `bg_map[((cy + scy//8) % 32) * 32 + (cx + scx//8) % 32]`; handle the partial column and row at the screen edge by emitting 21x19 cells and dropping any whose box is not fully inside 0..160 by 0..144 (so every emitted tile crop is a full 8x8). Cells whose top is above `skip_top_px` are dropped (Mario HUD).

### source_red.py

- Skip (`skip=True`) when `in_battle` is non-zero, or when no NPC slot read is sane. Also skip when the screen is a menu or text box: if you cannot detect it cheaply, do not guess, and leave it recorded (the dedupe cap bounds the damage); say in the Report what you did.
- Sprites: for slots 1 to 15 with a non-zero picture id and image index not 0xFF, the box is 16x16 at screen pixel `x = 64 + (npc_x - player_x) * 16`, `y = 60 + (npc_y - player_y) * 16` (the player stands at screen pixel (64, 60) in this game). Label = picture id, `coarse = "item"` when picture id equals `BALL_PIC`, else `"npc"`. `ident = f"slot{i}"`, `move` = the raw byte at 0xC206 + 16*i. Boxes entirely off screen are dropped. Also add the player (slot 0) as `coarse="player"`, label = its picture id, so a model can learn it.
- Background tile cells use the visible map from `bgmap.py`: the map select bit from LCDC, the 1024 bytes at 0x9800 or 0x9C00, SCX/SCY read from 0xFF43/0xFF42. `bank` = the byte at 0xD367. Coarse for every tile is `"terrain"`. A tile cell overlapping any sprite box is not emitted (its pixels contain a sprite).
- `area = f"map-{map_id}"`.

### source_mario.py

- Skip when lives byte reads 0 or the world-level byte is 0 (title, transitions). Boot presses: START three times with hold 8, settle 60.
- Sprites: every on-screen OAM box from `oam.py`, label = tile id, `ident = f"oam{index}"`, `move=None`. Coarse is provisional because no table of Mario tile ids exists in the repo and the worktree cannot measure one: a box whose x is within 12 pixels of RAM Mario x (0xC202) and whose y is within 20 of RAM Mario y minus 16 is `"player"`; every other box is `"enemy"`. The class table lives in a data file `src/pokeagent/vision/coarse_overrides.json` <!-- new: src/pokeagent/vision/coarse_overrides.json --> shaped `{"mario-land": {"<tile id>": "item"}}`, shipped as `{}`; the source applies an override when present. Claude measures real tile ids with the ROM afterwards and fills it in; the code path and its test must exist now.
- Background tiles from `bgmap.py` with `skip_top_px=16`, `bank = None`, coarse `"terrain"`, skipping cells that overlap a sprite box.
- `area = f"{world}-{level}"` from the world-level byte, `player = (level_progress, mario_y)`, computed exactly as in the formula above from `read` calls (do not import PyBoy).

### crops.py and store.py

- `crop(frame: np.ndarray, x, y, w, h) -> np.ndarray | None` returns an `(h, w, 3)` uint8 array copy, or `None` when the box is not fully on screen. Frame is `(144, 160, 3)`.
- `content_id(arr) -> str` is `sha1(bytes([w, h]) + arr.tobytes())` hex.
- `thumb(frame) -> np.ndarray` 72x80 greyscale (mean of 2x2 blocks of the luminance, integer arithmetic) and its id.
- `Store(root, *, max_bytes=200_000_000, max_per_key=40, max_thumbs=3000)`: `add_crop(kind, label, coarse, area, region, x, y, w, h, bank, arr)` writes `images/<hh>/<sha1>.png` once per content id (check an in-memory set first, never stat per call), and increments the `count` of its `(kind, label, area, id)` row; it refuses a NEW image (still counting existing ones) when the running byte total passes `max_bytes` or when the `(kind, label, area)` key already holds `max_per_key` distinct images (so a common terrain tile cannot fill the disk, while rare labels keep all their variants). `add_thumb` follows the same rules with `max_thumbs`. The byte total is the sum of bytes actually written plus index sizes, kept in memory. `flush()` writes `samples.jsonl`, `thumbs.jsonl` and `meta.json` atomically (write a temp file in the same directory, then `os.replace`, retry up to 40 times on `PermissionError` with a 50 ms sleep, as `tools/mario_maps.py` `write_atomic` does). PNG writes are done through Pillow, one file per unique image.
- Everything in `store.py` is keyed by content: re-running the recorder into an existing root must continue from the existing `samples.jsonl` (load it at open), not duplicate it.

### positions.py

`PositionLog(root, *, max_bytes=50_000_000)`: `append(frame, run, area, player, ents)` writes one JSON line; when the cap is reached it stops appending and sets `capped = True` (recorded in `meta.json`). One file handle, line buffered, closed by `close()`. Entities are logged for every sampled frame, not only on change, so a stationary NPC shows as a repeated position (directive 3 needs the stationary examples).

### driver.py

- `ScriptDriver(path)`: JSON `{"game":..., "start_state": "<path or null>", "presses": [["right", 8, 16], ...]}`; the button strings are the `Button` enum values in `emulator.py`. `iter_presses()` yields `(Button, hold, settle)`.
- `RandomWalkDriver(seed, n_presses, buttons)`: a seeded `random.Random(seed)` choosing among up/down/left/right/a/b with holds 8 and settle 16, deterministic for a seed. Default for Red is directions only plus `a` every ~10th press.
- No game logic in either; they only emit presses.

### record.py

`record(emu, source, store, positions, presses, *, sample_every=8, thumb_every=30, run="run") -> dict` returns counters. For every press: call `emu.press(button, hold, 0)` (registers the hold; a zero settle ticks nothing), then run the settle frames plus the hold frames in chunks of `sample_every` with `emu.tick_rendered(chunk)`. After each chunk call `source.read(emu)`; skip the frame when `labels.skip`, else take `frame_rgb()` once, reshape to (144, 160, 3), add every sprite crop and tile crop to `store`, append the positions line, and every `thumb_every` samples add a thumbnail with `labels.cell` and `labels.player`. The emulator's behaviour for the game under record is therefore the same as a normal run: press, hold, settle. Tests with a fake emulator assert the loop calls and the counters; the loop must stop cleanly when `store` reports it is full AND the positions log is capped.

### tools/vision_record.py

`uv run python tools/vision_record.py --game pokemon-red --rom "roms/Pokemon Red.gb" --state <path> --presses 2000 --seed 1 [--script file.json] [--out runs/vision/pokemon-red] [--max-mb 200] [--sample-every 8] [--run name]`. Behaviour: open `PyBoyEmulator(rom, headless=True)` (never a window), tick 60, load the state if given (then tick 30), else apply `source.boot_presses`; build the driver; call `record`; `flush()`; print the counters and the output size. `--out` is checked: the resolved path must be inside a `runs` directory under the current working directory, else exit with an error (this keeps the dataset out of tracked paths). Importing the file must not import PyBoy (import inside `main`) so tests can import it.

### Legal and gitignore

Add these lines to `.gitignore`, under the existing `runs/` group, with a one-line comment that they are ROM-derived: `runs/vision/`, `runs/vision_models/`, `*.pt`, `*.pth`, `*.npz`. (`runs/` is already ignored; the explicit entries survive if that line is ever narrowed.) Add one sentence to `docs/LEGAL.md` under "What is never in this repository": crops, thumbnails, datasets and trained weights derived from a game are local only. Do not name where any game copy came from.

## What NOT to do

- Do not change `src/pokeagent/emulator.py`, `ram.py`, `ramstructs.py`, anything under `explorer/`, `agent.py`, the control API, or any file the agent loop imports. The recorder is a separate process: it never runs inside, beside or against a live agent.
- Do not change any default path or flag of the Pokemon Red code; `git diff --stat main -- src/pokeagent` must list only new files under `src/pokeagent/vision/`.
- Do not touch `tools/mario_maps.py`, `tools/watch_game.py`, `tools/watch_mario_land.py` or any other Mario or Pokemon tool.
- Do not touch `roms/` or `baselines/` and do not read any ROM or save state in tests; no test may need a ROM.
- Do not commit any image, dataset, thumbnail or model. Fixtures are generated inside the test with `tmp_path`.
- Do not add a dependency; numpy and Pillow are present. No torch here.
- No window, no input event, no network. No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Do not state in code, comments, docs or the report where any game copy came from.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run python --version
uv run pytest -q tests/test_vision_oam.py tests/test_vision_bgmap.py tests/test_vision_sources.py tests/test_vision_store.py tests/test_vision_positions.py tests/test_vision_driver.py tests/test_vision_record.py tests/test_vision_dataset.py tests/test_vision_legal.py
```
Expected: all pass.

```
git diff --stat main -- src/pokeagent
```
Expected: only added files under `src/pokeagent/vision/`.

```
uv run pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Tests open no window, need no ROM, and generate their fixtures: a `FakeEmulator`-style stub whose memory dict holds a fabricated OAM block (160 bytes at 0xFE00), a fabricated 1024-byte background map, the sprite-table bytes, and a frame supplied by a stub `frame_rgb()` made of a gradient so crops differ.
- Branch only (`directive/pokeagent-vision-label-recorder-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and line counts in the Report.

## Completion criteria

- [ ] `on_screen_boxes` returns the right boxes for a fabricated OAM: 8x8 and 8x16 modes, partially off-screen entries kept, fully off-screen dropped, and the 16-high label has bit 0 cleared. <!-- test: tests/test_vision_oam.py -->
- [ ] `visible_cells` returns only full 8x8 cells, honours SCX/SCY wrap at 256 and the map-select bit, and drops cells above `skip_top_px`. <!-- test: tests/test_vision_bgmap.py -->
- [ ] The Red source, on a fabricated sprite table, returns the NPC boxes at the pixel positions given by the formula, marks a ball picture as `item`, drops hidden slots, includes the player, skips in battle, and emits no tile cell that overlaps a sprite; the Mario source skips at zero lives, marks the box near Mario as `player` and others `enemy`, and applies a `coarse_overrides.json` entry (test passes an override mapping in directly). `get_source` raises a clear error for an unknown game and `SOURCES` holds exactly the two games. <!-- test: tests/test_vision_sources.py -->
- [ ] `Store` writes one PNG per unique content, increments `count` for repeats without rewriting, enforces `max_bytes` and `max_per_key` for new images only, flushes atomically, and a second `Store` on the same root continues the first one's counts instead of duplicating. <!-- test: tests/test_vision_store.py -->
- [ ] `PositionLog` writes one line per call with the contract keys, stops at its cap and reports `capped`, and logs a stationary entity on every sampled frame. <!-- test: tests/test_vision_positions.py -->
- [ ] `ScriptDriver` reads the JSON shape and `RandomWalkDriver` is deterministic for a seed and different for another seed. <!-- test: tests/test_vision_driver.py -->
- [ ] `record` over a stub emulator produces counters, crops, positions lines and thumbnails in the contract layout, stops when the store and the log are both full, and `tools/vision_record.py` imports without importing PyBoy and rejects an `--out` outside a `runs` directory. <!-- test: tests/test_vision_record.py -->
- [ ] `dataset.py` reads back a store written by the tests, tolerates a truncated last line in each jsonl file, `load_image` returns an `(h, w, 3)` uint8 array, and `load_thumb` an `(72, 80)` uint8 array. <!-- test: tests/test_vision_dataset.py -->
- [ ] `.gitignore` contains the five new entries, `docs/LEGAL.md` has the added sentence, and the diff contains no image, `.npz`, `.pt` or `.pth` file. <!-- test: tests/test_vision_legal.py -->
- [ ] Every new file is under its stated line limit and `git diff --stat main -- src/pokeagent` shows only new files under `src/pokeagent/vision/`.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, line counts of each new file, what the Red source does about menus and text boxes, any address in this directive you changed or doubted, and the constants chosen. Then the checks Claude runs afterwards with the ROM (Claude's lane; Devin cannot do them):

1. Run `tools/vision_record.py` for Pokemon Red from a real state for ~2000 presses and for Super Mario Land from boot, with the real ROMs, and open ten crops per class by eye: sprite crops must contain the sprite, tile crops must be full 8x8 background.
2. Cross-check the Red box formula and the OAM reading against PyBoy's own `pyboy.get_sprite(i)` and `pyboy.tilemap_background` on the same frames; fix the formula in a follow-up if they disagree.
3. Verify the 0xD367 tileset byte and the 0xC206 movement byte against a known map, and fill `coarse_overrides.json` for Mario from the measured tile-id frequencies.
4. Check dataset size and the dedupe ratio, and confirm `git status` shows nothing under `runs/`.

## Forbidden Actions

- ROMs, extracted game art, datasets, thumbnails, trained weights and anything derived from them are ROM-derived: they stay local and gitignored. Never commit them, never add them to a fixture, never publish them.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not edit `src/pokeagent/emulator.py`, `src/pokeagent/cli.py`, `src/pokeagent/explorer/`, `roms/`, `baselines/`, or any Mario or Pokemon tool under `tools/`.
- Do not run any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a window or send input in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The ROM checks in the Report section, run by Claude after the verify lane passes. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run python --version)
- Exec(uv run pytest)
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
- 2026-11-08 13:21 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert: RAM-labelled vision dataset recorder (directive 1 of 3)
<!-- queue:end -->
