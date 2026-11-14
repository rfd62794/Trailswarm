# PokeAgent: vision semantic labels - a ROM-derived walkable / solid / grass / counter / ledge / npc / item / player layer so the cheap vision model is scored on classes that exist in every tileset

## Why this exists

Robert, 2026-11-08, approved the cheap local vision model (`Cheap_Sprite_Model_Directive.md`, merged as #258). Its first real run on the laptop, 2026-11-14, `uv run python tools/vision_train.py --game pokemon-red --threads 4 --max-seconds 300`:

```
train areas (8): map-0, map-3, map-35, map-37, map-39, map-40, map-63, map-96
test areas  (3): map-101, map-64, map-66
rows: 6294 train / 1287 test (974 test rows dropped: image id also in a train area)
template: overall 0.096 macro 0.068 coarse 0.999 | unseen_in_train 573
net:      overall 0.022 (weighted 0.004) macro 0.022 coarse 0.998 | unseen_in_train 573
params 22817 | ms/crop 0.011 ms/frame 0.7
```

The cause is the label, not the model. A tile row is labelled by its raw tile id (`tile:<id>@<tileset>`), and tile ids only mean something inside one tileset: tile 44 is grass in one tileset and a wall in another. Held-out maps on other tilesets therefore have 573 of 1287 rows (45%) whose class never appears in training, and no model can score on a class it never saw. Coarse accuracy is 0.999 only because the coarse class is almost always `terrain`.

The fix is a SEMANTIC class that means the same thing in every tileset, taken from game data the repo already reads (no hand labelling): is this tile walkable, solid, tall grass, a shop counter, or a ledge; is this sprite the player, an NPC or an item ball. The model is then scored on that class with the same area-held-out split.

Rows in `runs/vision/<game>/samples.jsonl` (the dataset is gitignored, ROM-derived and NOT in your worktree; you cannot run a ROM; everything below is testable with synthetic inputs):

```
{"id":"<sha1>","kind":"tile","label":44,"coarse":"terrain","area":"map-0","region":"r0c0","x":0,"y":0,"w":8,"h":8,"count":3078,"bank":0}
{"id":"<sha1>","kind":"sprite","label":13,"coarse":"npc","area":"map-0","region":"r1c1","x":64,"y":60,"w":16,"h":16,"count":12,"bank":0}
```
For a tile row `label` is the tile id (the index the background map holds) and `bank` is the tileset id (the game's `wCurMapTileset`, 0..23). For a sprite row `label` is the sprite picture id, and `coarse` is one of `player`, `npc`, `item` (picture id 61 = pick-up ball), `enemy`, `other`.

## What the repo already knows (pasted; the worktree cannot be searched)

All of this is in `src/pokeagent/atlas/` and `src/pokeagent/legs/grid.py` on main.

1. Tileset header table, 24 entries of 12 bytes at ROM offset `0xC7BE` (`src/pokeagent/atlas/tiles.py`: `TILESETS, NUM_TILESETS, ENTRY = 0xC7BE, 24, 12`). Entry layout: byte 0 bank, 1-2 blockset pointer, 3-4 gfx pointer, 5-6 collision-list pointer, 7-9 three counter tile ids (0xFF = unused), 10 the tall-grass tile id (0xFF = none), 11 animation.
2. The walkable tile ids of a tileset, read from ROM bytes (`src/pokeagent/atlas/collision.py`):
```
TILESET_TABLE, ENTRY, NUM_TILESETS = 0xC7BE, 12, 24
def walkable_ids(rom: bytes, tileset: int) -> frozenset:
    """The walkable tile ids of ``tileset`` read from the ROM bytes (empty for an unknown tileset)."""
```
   It works on any `bytes` buffer, so a test can build a synthetic one. Verified here: a `bytearray` with the collision pointer `00 10` at entry 3 (`0xC7BE + 12*3 + 5`) and `05 06 07 FF` at offset `0x1000` gives `walkable_ids(bytes(rom), 3) == frozenset({5, 6, 7})`.
3. The blockset (`src/pokeagent/atlas/tiles.py`): `load_tileset(d: bytes, index: int) -> Tileset` with `Tileset.blockset` an `np.ndarray` of shape `(n_blocks, 4, 4)` of tile ids, row major. The player steps in 2x2-tile CELLS, and the game tests only the BOTTOM-LEFT tile of a cell against the collision list (`src/pokeagent/atlas/walkgrid.py`: `cell_tiles` takes `blockset[blocks][:, :, [1, 3]][:, :, :, [0, 2]]`, i.e. rows 1 and 3, columns 0 and 2 of the 4x4 block). So within a block, cell `(cy, cx)` (each 0 or 1) covers tiles at rows `2*cy, 2*cy+1` and columns `2*cx, 2*cx+1`, and its stepping tile is `block[2*cy+1][2*cx]`. Consequence you MUST respect: the collision list holds stepping-tile ids only. A tile id that appears in a cell's top row or right column may never be a stepping tile, so classifying a tile id by "is it in the collision list" would wrongly call most wall tops solid and most floor edges unknown. The class of a tile id is therefore taken from the CELLS it appears in (rule below).
4. Grass and ledges (`src/pokeagent/legs/grid.py`, ROM-checked there): the grass tile id is `rom[0xC7BE + 12*tileset + 10]` (0xFF = none; a cell is tall grass when its stepping tile equals it). The ledge table, importable as `from pokeagent.legs.grid import LEDGES`:
```
# pokered LedgeTiles (ROM 0x1A6CF, checked in tests): (facing, tile stood on, ledge tile in front). Overworld tileset (0) only.
LEDGES = {("DOWN", 0x2C, 0x37), ("DOWN", 0x39, 0x36), ("DOWN", 0x39, 0x37), ("LEFT", 0x2C, 0x27), ("LEFT", 0x39, 0x27),
          ("RIGHT", 0x2C, 0x0D), ("RIGHT", 0x2C, 0x1D), ("RIGHT", 0x39, 0x0D)}
```
   The third element is the ledge tile in front (the one you hop over): `{0x37, 0x36, 0x27, 0x0D, 0x1D}`. A ledge cell is a NON-walkable cell on tileset 0 whose stepping tile is one of those.
5. Counters: header bytes 7-9 (item 1). They are not in the collision list.
6. Sprites: `src/pokeagent/vision/source_red.py` already sets `coarse` to `player` (slot 0), `item` (picture id `BALL_PIC = 61`) or `npc` (everything else). The semantic sprite class is that coarse value.

NOT determinable from data the repo reads today, so NOT in the vocabulary (do not invent constants for them): water, warp/door tiles, signs, trees, buildings. Water and trees are simply non-walkable, so they land in `solid`; door and warp tiles are walkable tiles in the collision list, so they land in `walkable`. Say this in the module docstring so a later directive can add them.

## The semantic vocabulary and its rule

`SEMANTIC = ("walkable", "solid", "grass", "counter", "ledge", "npc", "item", "player", "other")` (this exact order; the index is the class id).

Cell class from its stepping tile `t` and the tileset's facts (precedence in this order):
1. `ledge` if the tileset is 0, `t` is in the ledge-front set above, and `t` is not walkable.
2. `grass` if `t` equals the grass tile id (0xFF means none) and `t` is walkable.
3. `counter` if `t` is one of the counter ids (0xFF means unused).
4. `walkable` if `t` is in the collision list.
5. otherwise `solid`.

Tile-id class: for one tileset, walk EVERY block of the blockset and EVERY one of its 4 cells; the cell's class (above, from its stepping tile) is credited to each of the 4 tile ids the cell covers. The tile id's class is the most credited class; a tie goes to the class earlier in `SEMANTIC`. A tile id credited nowhere (a font or HUD tile, an id past the blockset) is `other`. Also return how many tile ids were credited to more than one class (`ambiguous`), so Claude can see how clean the table is.

Row class: a sprite row gets `player`, `npc` or `item` from its `coarse`, plus `item` whenever its `label` is 61; any other sprite `coarse` (`enemy`, `other`) is `other`. A tile row gets the table lookup for `(row["bank"], row["label"])`; a `bank` that is `None` or has no table, or a tile id not in the table, is `other`.

## Scope (in this order)

1. `src/pokeagent/vision_model/semantic.py` <!-- new: src/pokeagent/vision_model/semantic.py --> - the vocabulary and the pure functions. No ROM, no torch, no file access. Under 140 lines.
2. `src/pokeagent/vision_model/semantic_rom.py` <!-- new: src/pokeagent/vision_model/semantic_rom.py --> - reads the facts out of ROM BYTES (a `bytes` argument, never a path) and builds the per-tileset tables. Under 90 lines.
3. `tools/vision_relabel.py` <!-- new: tools/vision_relabel.py --> - offline re-label tool: adds the `semantic` field to an existing `samples.jsonl`. Under 100 lines.
4. `src/pokeagent/vision_model/data.py` - `Dataset` gains an optional `semantic` column; `load_dataset` fills it from the rows when present. Minimal edit.
5. `src/pokeagent/vision_model/semantic_view.py` <!-- new: src/pokeagent/vision_model/semantic_view.py --> - turns a `Dataset` into the semantic view the existing split, template, net and metrics code can use unchanged. Under 60 lines.
6. `src/pokeagent/vision_model/metrics.py` - one added pure function `side_by_side`. Minimal edit.
7. `tools/vision_train.py` - the `--labels` flag. Minimal edit; the file stays under 150 lines.
8. `docs/KNOWLEDGE.md` - two sentences under the existing "Sprite model" paragraph.
9. Tests: `tests/test_vision_semantic.py`, `tests/test_vision_semantic_rom.py`, `tests/test_vision_relabel.py`, `tests/test_vision_semantic_view.py`, `tests/test_vision_train_semantic.py`. <!-- new: tests/test_vision_semantic.py --> <!-- new: tests/test_vision_semantic_rom.py --> <!-- new: tests/test_vision_relabel.py --> <!-- new: tests/test_vision_semantic_view.py --> <!-- new: tests/test_vision_train_semantic.py -->

## The work

### semantic.py (pure)

```
SEMANTIC = ("walkable", "solid", "grass", "counter", "ledge", "npc", "item", "player", "other")
LEDGE_FRONT = frozenset(t for _f, _s, t in LEDGES)        # from pokeagent.legs.grid import LEDGES
BALL_PIC = 61

@dataclass(frozen=True)
class TilesetFacts:
    tileset: int
    walkable: frozenset      # collision-list tile ids
    grass: int               # grass tile id, 0xFF = none
    counters: frozenset      # counter tile ids with 0xFF removed

def cell_class(tile: int, facts: TilesetFacts) -> str: ...        # the five-step precedence above
def tile_table(blockset: np.ndarray, facts: TilesetFacts) -> tuple[dict[int, str], int]: ...   # (tile id -> class, ambiguous count)
def sprite_class(label: int, coarse: str) -> str: ...
def row_class(row: dict, tables: dict[int, dict[int, str]]) -> str: ...   # tables: tileset id -> tile table
```
`tile_table` is vectorisable with numpy but a plain loop over `n_blocks * 4` cells is fine (at most 256 blocks per tileset). Keys of the returned dict are plain Python ints, values are members of `SEMANTIC`.

### semantic_rom.py (ROM bytes in, tables out)

```
def facts_from_rom(rom: bytes, tileset: int) -> TilesetFacts: ...
def tables_from_rom(rom: bytes, tilesets=range(24)) -> tuple[dict[int, dict[int, str]], dict[int, int]]: ...   # (tables, ambiguous count per tileset)
```
`facts_from_rom` uses `pokeagent.atlas.collision.walkable_ids(rom, tileset)` and header bytes 7-10 at `0xC7BE + 12*tileset` (import `TILESET_TABLE`, `ENTRY` from `pokeagent.atlas.collision`). `tables_from_rom` uses `pokeagent.atlas.tiles.load_tileset(rom, tileset).blockset`. A tileset whose header cannot be read (buffer too short) is skipped and absent from the result, never an exception for the whole call. The ROM path is NOT read here; the caller passes bytes.

### tools/vision_relabel.py

`uv run python tools/vision_relabel.py --root runs/vision/pokemon-red --rom "roms/Pokemon Red.gb" [--dry-run]` (the ROM path is whatever Claude passes; the tool takes it from the argument only and never prints where it came from). It:
1. refuses a `--root` that is not inside a `runs` directory under the current directory (copy the `out_in_runs(out, cwd)` rule of `tools/vision_record.py`: resolve the path, it must be under `cwd/runs`; return exit code 2 with a message otherwise);
2. reads `<root>/samples.jsonl` line by line (it needs no images), builds `tables_from_rom(Path(rom).read_bytes())`, and sets `row["semantic"] = row_class(row, tables)` on every row, leaving every other field byte-for-byte as it was (same key order, `semantic` appended last);
3. without `--dry-run`: first copies the old file to `samples.jsonl.pre-semantic` (only if that backup does not already exist), then writes the new file to `samples.jsonl.tmp` and renames it over `samples.jsonl` (`Path.replace`); with `--dry-run` it writes nothing;
4. prints a table of semantic class counts per kind (rows and sum of `count`), the number of tile rows that fell back to `other` because of a missing table or tile id, and the per-tileset `ambiguous` counts; exit code 0.
It must be idempotent (running it twice gives the same file). Put the work in `relabel(rows, tables) -> list[dict]` and `summarise(rows) -> str` functions so tests can call them without a file, and keep `main(argv=None)` thin.

### data.py (minimal)

Add to `Dataset` a last field `semantic: np.ndarray | None = None` (`(N,) int8` index into `SEMANTIC`, or `None`), carried through `select` (`None` stays `None`). `load_dataset` sets it only when EVERY loaded row has a `"semantic"` key whose value is in `SEMANTIC`; otherwise `None`. Do not change any existing field, dtype or default behaviour; the existing data tests stay green untouched.

### semantic_view.py

```
def as_semantic(ds: Dataset) -> Dataset: ...
def class_name(key: tuple) -> str: ...
```
`as_semantic` raises `ValueError("no semantic labels: run tools/vision_relabel.py first")` when `ds.semantic is None`. Otherwise it returns a copy (`dataclasses.replace`) with `label = ds.semantic.astype(int32)`, `kind` all zeros and `bank` all -1, so the existing `row_key` becomes `("sprite", -1, <semantic index>)` and ONE class table is shared by tiles and sprites; `images`, `coarse`, `area`, `weight`, `w`, `h`, `ids` are unchanged (the leak check by image id still works). `class_name((kind, bank, idx))` returns `SEMANTIC[idx]`.

### metrics.py (minimal)

`side_by_side(t_rep: dict, n_rep: dict) -> list[str]`: from two reports of the shape `evaluate` returns, one line per class that has support in either report, `f"{name:<10} n={support:<6} template={t_acc:.3f} net={n_acc:.3f}"` (support taken from the template report; a class missing from one report prints `-` for its accuracy), preceded by a header line `class      support   template  net`. Pure, no printing.

### tools/vision_train.py (minimal)

Add `--labels {specific,semantic}` with default `specific`. With `specific` the tool's behaviour, output and `report.json` stay exactly as today (a test asserts the specific path never calls `as_semantic`). With `semantic`: after `load_dataset`, `ds = as_semantic(ds)`; return exit code 2 with the `ValueError` message on stderr when there are no semantic labels; use `semantic_view.class_name` in place of `data.class_name` for the class names; everything else (area split, leak drop, template, net, evaluation, the printed `_print_report` blocks) is the same code path; after both reports print the `side_by_side` table; write `report.json` and weights under `runs/vision_models/<game>-semantic/` (so the specific model is not overwritten) with the extra key `"labels": "semantic"`. Do not add other flags.

The semantic tool run needs the same ~one-file change in the `names`/`full` construction only; if `data.class_name` is called in more than two places, route them all through one local `name_of = ...` chosen from the flag.

### docs/KNOWLEDGE.md

Two sentences in the "Sprite model" paragraph: `tools/vision_relabel.py` adds a `semantic` class (walkable, solid, grass, counter, ledge, npc, item, player, other) from the ROM collision list, grass/counter header bytes and ledge table, and `tools/vision_train.py --labels semantic` trains and scores on it; water, doors and signs are not in the vocabulary because the repo reads no tile-level data for them.

## What NOT to do

- Do not change the default (`--labels specific`) behaviour of `tools/vision_train.py`, `src/pokeagent/vision/`, `src/pokeagent/vision_model/net.py`, `split.py`, `template.py`, `bench.py`, `export.py`, `src/pokeagent/atlas/`, `src/pokeagent/legs/`, `src/pokeagent/emulator.py`, `cli.py`, the agent, or any Pokemon behaviour. `git diff --stat origin/main -- src/pokeagent` lists only: new `semantic.py`, `semantic_rom.py`, `semantic_view.py`, and edits to `data.py` and `metrics.py` under `src/pokeagent/vision_model/`.
- Do not hand-label anything and do not write a table of tile ids per tileset. The only constants allowed are the ones pasted above (`LEDGES` imported, `BALL_PIC`, the header offsets) and the vocabulary.
- Do not add water, door, sign or tree classes, and do not guess tile ids for them.
- Do not read `runs/`, `roms/` or `baselines/` in any test; no test may need a ROM or a dataset. ROM bytes in tests are synthetic `bytearray`s built in the test; samples files live under `tmp_path`.
- Do not import torch at module level anywhere; `tests/test_vision_train_semantic.py` that trains must use `pytest.importorskip("torch")` and skip without it (this worktree may not have torch).
- Do not split by random frame or row anywhere. Do not tune on the held-out areas.
- Do not run `uv lock`, `uv sync`, `pip` or any install or download. Do not add dependencies.
- Do not commit any dataset, weights, report, image or ROM-derived table. No window. No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Do not state where any game copy came from, in code, comments, docs, the report or commit messages.

## Verification (exact commands; Claude confirmed `uv run --frozen python --version` prints `Python 3.12.12` in this repo; do not run a bare version command, it is not in the sandbox list)

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_vision_semantic.py tests/test_vision_semantic_rom.py tests/test_vision_relabel.py tests/test_vision_semantic_view.py tests/test_vision_train_semantic.py
```
Expected: all pass; the torch-gated test is reported skipped when torch is absent, and that is acceptable here.

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_vision_model_data.py tests/test_vision_model_split.py tests/test_vision_model_template.py tests/test_vision_model_metrics.py tests/test_vision_model_net.py tests/test_vision_model_bench.py tests/test_vision_model_imports.py tests/test_vision_dataset.py
```
Expected (Claude ran this on origin/main before writing the directive): `16 passed, 6 skipped`. After your change the passed count may only grow; skipped may only be the torch tests.

```
git diff --stat origin/main -- src/pokeagent pyproject.toml
```
Expected: only the files named under "What NOT to do". `pyproject.toml` and `uv.lock` are unchanged.

```
uv run --frozen pytest -q -p no:cacheprovider
```
Expected: no new failures against main; ROM-gated tests skip in this worktree.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row. Every fact you need is pasted above.
- Use `uv run --frozen` for every command. Never a bare `python`.
- Branch only (`directive/pokeagent-vision-semantic-labels-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and line counts in the Report.

## Completion criteria

- [ ] `cell_class` applies the five-step precedence (ledge only on tileset 0 and only when not walkable; grass only when walkable and equal to the grass id, 0xFF meaning none; counter ids with 0xFF ignored; walkable; solid). <!-- test: tests/test_vision_semantic.py -->
- [ ] `tile_table` credits each cell's class to all four tiles the cell covers, uses the bottom-left tile (`block[2*cy+1][2*cx]`) as the stepping tile, breaks ties toward the earlier `SEMANTIC` class, returns `other` for uncredited ids via `row_class`, and counts ambiguous ids; a synthetic blockset where a wall-top tile is not in the collision list still comes out `solid` and a floor-edge tile that is only ever a non-stepping tile of a walkable cell comes out `walkable`. <!-- test: tests/test_vision_semantic.py -->
- [ ] `row_class` maps sprites from `coarse` (and label 61 to `item`), unknown sprite coarse values to `other`, tile rows through `(bank, label)`, and a `None` bank or missing id to `other`. <!-- test: tests/test_vision_semantic.py -->
- [ ] `facts_from_rom` and `tables_from_rom` work on a synthetic ROM `bytearray` (collision list, grass byte, counter bytes, blockset), skip an unreadable tileset instead of raising, and never open a file. <!-- test: tests/test_vision_semantic_rom.py -->
- [ ] `relabel` adds `semantic` last without disturbing other fields, is idempotent, and the tool refuses a root outside `runs`, writes a `samples.jsonl.pre-semantic` backup once, does nothing under `--dry-run`, and prints the per-kind class counts and the fallback count. <!-- test: tests/test_vision_relabel.py -->
- [ ] `Dataset.semantic` is filled only when every row has a valid `semantic` value; `as_semantic` raises the documented `ValueError` without it and otherwise yields one shared class table across tiles and sprites with the same ids and areas; `class_name` returns the semantic name. <!-- test: tests/test_vision_semantic_view.py -->
- [ ] `side_by_side` lists every class with support, prints `-` for a class missing from one report, and `tools/vision_train.py --labels semantic` on a tiny synthetic relabelled dataset under `tmp_path` runs the template baseline and writes nothing outside `runs/vision_models/<game>-semantic/`; the default path never calls `as_semantic`; the net part skips without torch. <!-- test: tests/test_vision_train_semantic.py -->
- [ ] Every new file is under its stated line limit, torch is imported nowhere at module level, and the existing vision tests still pass with the counts above; Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails (state which tests skipped for lack of torch), line counts of each new file, and anything the rules above left ambiguous that you had to decide. Then the checks Claude runs afterwards with the ROM and torch (Claude's lane; Devin cannot do them):

1. `uv run python tools/vision_relabel.py --root runs/vision/pokemon-red --rom <rom> --dry-run`, read the class counts; then run it for real on the existing 8-train / 3-test dataset (backup `samples.jsonl.pre-semantic` is kept).
2. Sanity-check the table against the screen: open 3 or 4 crops per class (walkable, solid, grass, counter, ledge) as images and check the label is right; check the per-tileset `ambiguous` counts are small and that tile rows falling back to `other` are font or HUD tiles, not floor.
3. Confirm the assumption that a tile row's `label` equals the blockset tile id (grass crops should be grass; if tiles look systematically wrong the label offset is the fault, not the model).
4. `uv sync --group vision` if needed, then `uv run python tools/vision_train.py --game pokemon-red --labels semantic --threads 4 --max-seconds 300`: read overall, macro, coarse, `unseen_in_train` (it should now be near zero) and the side-by-side per-class table against the 2026-11-14 baseline above (template 0.096, net 0.022).
5. Re-record with the ROM (`tools/vision_record.py`) for more maps and tilesets and run `vision_relabel.py` again (a fresh recording has no `semantic` field); then retrain and compare held-out maps on other tilesets.
6. Decide whether water, doors and signs are worth a follow-up directive (they need tile-level data the repo does not read yet).
7. Confirm `git status` shows no weights, report, image or ROM-derived file outside gitignored paths.

## Forbidden Actions

- ROMs, extracted game art, datasets, trained weights, tile tables dumped from a ROM and anything derived from them are ROM-derived: they stay local and gitignored. Never commit them, never add them to a fixture, never publish them.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not edit `src/pokeagent/vision/`, `src/pokeagent/atlas/`, `src/pokeagent/legs/`, `src/pokeagent/emulator.py`, `src/pokeagent/cli.py`, `roms/`, `baselines/`, or any Mario or Pokemon tool under `tools/` other than the two named here.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a window or send input in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- `Cheap_Sprite_Model_Directive.md` merged (it is: #258) so `src/pokeagent/vision_model/` exists on the base. If `git grep -n "def class_table" -- src/pokeagent/vision_model/data.py` finds nothing at the start of the run, stop and write that in the Status row.
- The ROM and torch checks in the Report section, run by Claude after the verify lane passes. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-14 12:39 · robert-claude-laptop · none → Queued
- 2026-11-14 12:40 · robert-claude-laptop · Queued → Approved
<!-- queue:end -->
