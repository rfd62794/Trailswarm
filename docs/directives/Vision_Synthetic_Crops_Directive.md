# PokeAgent: Vision synthetic crops - render exactly-labelled 8x8 tile and 16x16 sprite crops from ROM graphics, and mix a capped share into TRAIN only so the held-out score stays organic

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Depends on:** `Vision_Semantic_Labels_Directive.md` for the semantic label ONLY (`src/pokeagent/vision_model/semantic.py` <!-- new: src/pokeagent/vision_model/semantic.py -->, `src/pokeagent/vision_model/semantic_rom.py` <!-- new: src/pokeagent/vision_model/semantic_rom.py -->). That dependency is OPTIONAL: check with `git ls-files src/pokeagent/vision_model/semantic.py`. If it prints nothing, build the specific labels only, leave the semantic field out of every synthetic row, say "semantic label: not available, dependency not merged" in the PR description, and do NOT recreate those modules. **Independent of** `Vision_Error_Triage_Directive.md` (it edits the same `tools/vision_train.py` block that predicts and reports; see "Branch status" below). Base: current main.

**Read first:** `docs/directives/Vision_Semantic_Labels_Directive.md` (the semantic vocabulary and the tile and sprite facts), `docs/directives/Cheap_Sprite_Model_Directive.md`, `src/pokeagent/atlas/tiles.py`, `src/pokeagent/atlas/sprites.py`, `src/pokeagent/vision/source_red.py`, `src/pokeagent/vision_model/data.py`, `src/pokeagent/vision_model/split.py`.

## Standing rule for synthetic data (Robert, 2026-11-07, verbatim)

"We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."

Applied here: synthetic crops may TRAIN, TEST and DRILL the model but never decide truth. They are never scored on (evaluation is always organic held-out data), and a synthetic-trained model is never promoted on a synthetic number. Every synthetic row carries a provenance tag. Reports show organic and synthetic side by side. The synthetic share of any training mix is capped by a config constant. ROM-derived data stays local and gitignored.

## 1. Why this exists

Robert, 2026-11-14, approved. The cheap vision model's first real run (`uv run python tools/vision_train.py --game pokemon-red --threads 4 --max-seconds 300`, quoted in `docs/directives/Vision_Semantic_Labels_Directive.md`):

```
train areas (8): map-0, map-3, map-35, map-37, map-39, map-40, map-63, map-96
test areas  (3): map-101, map-64, map-66
rows: 6294 train / 1287 test (974 test rows dropped: image id also in a train area)
template: overall 0.096 macro 0.068 coarse 0.999 | unseen_in_train 573
net:      overall 0.022 (weighted 0.004) macro 0.022 coarse 0.998 | unseen_in_train 573
```

573 of 1287 held-out rows are classes the model never saw, because the recorder only sees the tiles and sprites of the maps it walked. But the ROM holds EVERY tile of every tileset and EVERY overworld sprite picture, and the repo already decodes them. Rendering those directly gives the model a labelled example of every class, including ones no recorded area contains, at zero emulator cost and with the label known exactly (it is the index it was rendered from, not a guess).

This is also the first test of the standing rule above: the held-out split stays organic, so whether synthetic data helped is measured on real frames, side by side with the organic-only result.

## 2. What the repo already reads from the ROM (pasted; the worktree cannot be searched)

Run `uv run python --version` first: it prints `Python 3.12.12`.

```
# src/pokeagent/atlas/tiles.py  (pure functions on a bytes buffer)
TILESETS, NUM_TILESETS, ENTRY = 0xC7BE, 24, 12
TILE_COUNT, BLOCK_BYTES, MAX_BLOCKS = 0x60, 16, 256
GREY = np.array([255, 170, 85, 0], dtype=np.uint8)     # Gen 1 BGP 0xE4: white, light, dark, black
@dataclass(frozen=True)
class Tileset:  index: int; blockset: np.ndarray (n_blocks,4,4) tile ids; tiles: np.ndarray (256,8,8) uint8 shade index 0..3
def decode_tiles(raw: bytes, count: int = 256) -> np.ndarray          # (count, 8, 8) shade indexes; missing tiles stay 0
def tileset_entry(d: bytes, index: int) -> tuple[int, int, int]       # (bank, blockset ptr, gfx ptr)
def load_tileset(d: bytes, index: int) -> Tileset
# src/pokeagent/atlas/sprites.py
SPRITE_SHEETS, ENTRIES, BANK = 97063, 70, 0x4000                      # picture ids 1..70; 1 = the player
def sheet(rom: bytes, sprite_id: int) -> np.ndarray                   # (frames,16,16) shade indexes: 6 (stand d/u/l, walk d/u/l) when it walks, else 3; ValueError for an id outside 1..70
def pick_frame(frames, facing: str, walk_phase: int = 0) -> np.ndarray # facing UP/DOWN/LEFT/RIGHT; RIGHT is the LEFT frame mirrored
```
Shade 0 (white) is transparent for a sprite on the overworld. Tile graphics: 0x60 tiles are loaded per tileset, 16 bytes each, 2bpp.

How the organic rows are labelled (this is what a synthetic row must match EXACTLY, because the model's class id comes from `row_key`):

```
# src/pokeagent/vision_model/data.py
def row_key(ds, i) -> tuple:   # (kind, bank, label)  kind "tile" or "sprite"; a tile id only means something inside its bank
def class_table(ds) -> dict    # dense id per distinct row_key
# src/pokeagent/vision/crops.py
def content_id(arr) -> str     # sha1 hex of (width, height, raw bytes)
# src/pokeagent/vision/store.py
def write_atomic(path: Path, write) -> None    # temp file beside path, then os.replace
# src/pokeagent/vision/record.py calls, per organic crop:
#   store.add_crop("sprite", s.label, s.coarse, labels.area, region, x, y, 16, 16, None, arr)   -> sprite bank is None, stored -1
#   store.add_crop("tile",   t.label, "terrain", labels.area, region, x, y, 8, 8, labels.bank, arr) -> bank = the map's tileset id
# one samples.jsonl row per unique crop, keys: id, kind, label, coarse, area, region, x, y, w, h, count, bank
```
So a synthetic TILE of tile id T in tileset S is the class key tile, S, T (the same class an organic crop of that tile gets), and a synthetic SPRITE of picture id P is the class key sprite, -1, P. The `coarse` of a synthetic tile is `terrain`; of a synthetic sprite it is `player` for picture id 1, `item` for picture id 61 (`BALL_PIC` in `src/pokeagent/vision/source_red.py`), else `npc`.

The training and scoring path in `tools/vision_train.py` today (class ids from `table`; test rows whose key is not in `table` get fresh ids and the name suffix " (unseen)"):

```
    train_areas, test_areas = split.split_by_area(ds.area, seed=a.seed)
    train_idx = split.area_indices(ds.area, train_areas)
    test_idx = split.area_indices(ds.area, test_areas)
    test_idx, removed = split.drop_leaking_test_rows(ds, train_idx, test_idx)
    split.assert_disjoint(train_idx, test_idx, ds)
    train_ds, test_ds = ds.select(train_idx), ds.select(test_idx)
    table = data.class_table(train_ds)
    ...
    res = net.train(ds, train_idx, table, epochs=a.epochs, seed=a.seed, threads=a.threads, max_seconds=a.max_seconds)
    n_lab, n_co = net.predict(res.model, test_ds.images)
    n_rep = metrics.evaluate(n_lab, y_true, n_co, test_ds.coarse, names, weight=test_ds.weight, coarse_names=data.COARSE, train_classes=set(table.values()))
```
`net.train(ds, train_idx, table, *, epochs=30, batch=128, lr=2e-3, seed=0, threads=1, max_seconds=300)` already augments with a plus or minus 1 px shift and a plus or minus 10 percent brightness jitter and does NOT flip horizontally (facing matters). `metrics.evaluate(...)` returns a report whose keys include overall, macro, coarse, per_class and `unseen_in_train` (a count of test rows whose true class id is not in `train_classes`); do not change it. `torch` is NOT installed in this worktree, so net tests skip; everything you add must be testable without torch.

## Branch status (checked 2026-11-14; build on main and keep your `tools/vision_train.py` edit minimal)

- `Vision_Error_Triage_Directive.md`: branch `directive/pokeagent-vision-error-triage-directive` is open and unmerged. It changes `tools/vision_train.py` in the import line and the predict-and-report block (`net.predict_with_confidence`, a `triage` key in the report).
- `Vision_Semantic_Labels_Directive.md`: branch `directive/pokeagent-vision-semantic-labels-directive` is open and unmerged. It adds a `--labels` flag, a `name_of` indirection for class names, and writes under a `-semantic` output folder in the same file.
- Neither is on main. Build on current main. Keep your `tools/vision_train.py` change to one new flag, one call into your new module placed right after the area split and before the class table is built, and one added key plus one printed block at the end, so a textual merge with either branch is a few lines. Put ALL logic in the new modules below, not in `tools/vision_train.py`. When the dependency lands the synthetic rows simply gain a semantic field; do not wire `--labels semantic` in this directive.

## 3. Scope (in this order)

1. `src/pokeagent/vision_model/synthetic.py` <!-- new: src/pokeagent/vision_model/synthetic.py --> - pure rendering: ROM bytes in, labelled crops out. No file access, no torch. Under 150 lines.
2. `src/pokeagent/vision_model/synthetic_store.py` <!-- new: src/pokeagent/vision_model/synthetic_store.py --> - writes the synthetic set under the runtime output folder and reads it back as a `Dataset`. Under 110 lines.
3. `src/pokeagent/vision_model/synthetic_mix.py` <!-- new: src/pokeagent/vision_model/synthetic_mix.py --> - the share cap, the TRAIN-only mix, and the organic-versus-with-synthetic comparison. Pure numpy. Under 120 lines.
4. `tools/vision_synth.py` <!-- new: tools/vision_synth.py --> - the offline tool that reads a ROM path from an argument and writes the set. Under 90 lines.
5. `src/pokeagent/vision_model/data.py` - ONE added pure function `concat(a, b)` joining two `Dataset` values; nothing else changes.
6. `tools/vision_train.py` - the `--synthetic-share` flag and the side-by-side block (minimal, see above).
7. `docs/KNOWLEDGE.md` - two sentences under the existing "Sprite model" paragraph.
8. Tests: `tests/test_vision_synthetic.py`, `tests/test_vision_synthetic_store.py`, `tests/test_vision_synthetic_mix.py`, `tests/test_vision_synth_tool.py`, `tests/test_vision_train_synthetic.py` <!-- new: tests/test_vision_synthetic.py --> <!-- new: tests/test_vision_synthetic_store.py --> <!-- new: tests/test_vision_synthetic_mix.py --> <!-- new: tests/test_vision_synth_tool.py --> <!-- new: tests/test_vision_train_synthetic.py -->.

## 4. The work

### 4.1 `src/pokeagent/vision_model/synthetic.py` (pure)

```
SYNTHETIC_SHARE_CAP = 0.5        # config constant: the most any training mix may be synthetic (fraction of TRAIN rows)
PROVENANCE = "synthetic"
SHIFTS = (-1, 0, 1)              # 1-px shifts on each axis (9 offsets)
BRIGHTNESS = (0.9, 1.0, 1.1)     # plus or minus 10 percent
PALETTES = (GREY,)               # shade ramps, each 4 uint8 values for shades 0..3; see note

@dataclass(frozen=True)
class SynthCrop:
    kind: str            # "tile" or "sprite"
    label: int           # tile id, or sprite picture id
    bank: int | None     # tileset id for a tile, None for a sprite (stored -1 by the reader, as organic does)
    coarse: str          # "terrain", or "player" / "item" / "npc"
    area: str            # "synthetic-tileset-<n>" or "synthetic-sprite"
    semantic: str | None # the semantic class when the dependency is present, else None
    variant: str         # human readable: palette index, shift, brightness
    image: np.ndarray    # (h, w, 3) uint8, h = w = 8 for a tile and 16 for a sprite

def render_tile(shades: np.ndarray, palette, dx: int = 0, dy: int = 0, gain: float = 1.0) -> np.ndarray: ...
def render_sprite(shades: np.ndarray, palette, dx: int = 0, dy: int = 0, gain: float = 1.0) -> np.ndarray: ...
def tile_crops(rom: bytes, tilesets=range(24), tables=None) -> Iterator[SynthCrop]: ...
def sprite_crops(rom: bytes, ids=range(1, 71)) -> Iterator[SynthCrop]: ...
def all_crops(rom: bytes, tables=None) -> Iterator[SynthCrop]: ...
```
Rules:
- Tiles: for every tileset in range 24 that `pokeagent.atlas.tiles.load_tileset(rom, index)` can read (a buffer too short for that header is SKIPPED, never an exception for the whole call), render EVERY tile id that tileset loads (`tiles` is 256 by 8 by 8; only ids below `TILE_COUNT` carry real graphics, so render ids 0 to `TILE_COUNT - 1` and nothing past it). One crop per (tile id, palette, dx, dy, gain).
- Sprites: for every picture id in `ids` render EVERY frame `pokeagent.atlas.sprites.sheet(rom, id)` returns (stand and walk, all directions; a `ValueError` or an unreadable entry skips that id only). A frame is 16 by 16. No horizontal flip as an augmentation. The game's own right-facing frame IS the left frame mirrored and `pick_frame` produces it: include the `RIGHT` frame that `pick_frame` returns for facing `RIGHT` as its own frame, because it is a real picture the game draws (it is not an augmentation); do not mirror anything else.
- Shifts and brightness: apply each of the 3 by 3 pixel offsets (np.roll is wrong, it wraps; shift with edge fill using the palette's shade 0 colour) and each gain (multiply the RGB by the gain, clip to 0..255, round, uint8). Gain 1.0 and shift 0,0 is the plain crop and must be emitted first.
- Sprite background: shade 0 is transparent on the overworld, so composite the sprite over a flat background of the palette's shade 0 colour. Do not invent scenery behind it.
- Palette note: `GREY` (the Gen 1 background ramp) is the baseline and the only palette the repo defines. `PALETTES` is a tuple so a later directive can add a ramp; do NOT invent colour values. Whether the emulator renders these exact greys is unverified from here: say so in the module docstring, and the organic check (section 4.7) is what confirms it.
- Semantic label: when `tables` is given (the `tables` output of `tables_from_rom` from the dependency, tileset id to tile id to class) set `semantic` for a tile from it, and for a sprite from the same `sprite_class` rule the dependency defines. With `tables=None`, `semantic` is None. Never import the dependency at module top: import it inside the function that needs it, so this module imports cleanly when the dependency is absent.
- The SPECIFIC label is always set (section 2 explains the class key). Both labels are exact because they are the index each crop was rendered from.
- Deterministic: the same ROM bytes give the same crops in the same order. No randomness anywhere in this file.

### 4.2 `src/pokeagent/vision_model/synthetic_store.py`

Layout, all under the runtime output folder `runs/vision/<game>/synthetic/` (a runtime output: gitignored by the `runs/` rule, never committed, not present in your worktree, so tests write under `tmp_path`): the same shape as an organic dataset root, so `data.load_dataset` and `pokeagent.vision.dataset.iter_samples` read it unchanged.

- `images/<hh>/<sha1>.png` one file per unique crop (content id from `pokeagent.vision.crops.content_id`; write PNGs with PIL as `pokeagent.vision.store` does).
- `samples.jsonl` one row per unique crop with the SAME keys an organic row has (id, kind, label, coarse, area, region, x, y, w, h, count, bank; `region` the string `synthetic`, x and y 0, `count` 1, `bank` the tileset id for a tile and null for a sprite) PLUS two extra keys: `provenance` (always the string `synthetic`) and, when available, `semantic`. Extra keys are ignored by the existing `data.load_dataset`, so the organic loader and every existing test are unaffected.
- `meta.json` with `provenance` set to `synthetic`, the crop count, and the generation constants (palettes count, shifts, brightness). Never record where the ROM came from, and never its path.
- Write through `pokeagent.vision.store.write_atomic` (temp file then replace). The store is rebuilt whole each time (it is derived data), so a second run with the same ROM bytes produces byte-identical `samples.jsonl` (assert this).
- `load_synthetic(root) -> Dataset`: returns a `Dataset` through `data.load_dataset(root)` and refuses (raises `ValueError`) any root whose `meta.json` does not say `synthetic`, so an organic root can never be loaded as synthetic by mistake.
- A hard cap: a `max_bytes` argument (default 200,000,000, the same figure `pokeagent.vision.store.MAX_BYTES` uses) stops adding new PNGs past it and the writer reports how many crops were skipped. Distinct crops dedupe by content id, so palette, shift and brightness variants that render identically are stored once.

### 4.3 `src/pokeagent/vision_model/synthetic_mix.py` (pure numpy)

```
def capped_share(requested: float, cap: float = SYNTHETIC_SHARE_CAP) -> float: ...       # clamp to 0..cap; a value above cap is clamped and the caller prints that it was
def mix_indices(n_organic_train: int, n_synthetic: int, share: float, seed: int) -> np.ndarray: ...
def combine(organic: Dataset, synthetic: Dataset) -> tuple[Dataset, np.ndarray]: ...
def covered_unseen(table_organic: dict, table_mixed: dict, test_keys) -> dict: ...
def compare(org_rep: dict, mix_rep: dict) -> dict: ...
def format_text(cmp: dict) -> str: ...
```
- `mix_indices` returns indices into the synthetic set (sorted, no repeats) of size `round(share * n_organic_train / (1 - share))` limited to `n_synthetic`; `share` 0 returns an empty array. This makes the synthetic fraction of the final TRAIN rows equal `share` (or less when the set is smaller). Sampling is seeded (`numpy.random.default_rng(seed)`) and stratified so every distinct class key present in the synthetic set that is NOT in the organic train set is represented first (these are the classes the mix exists to add), then the rest fills the quota at random.
- `combine(organic, synthetic)` uses `data.concat` and returns the joined `Dataset` plus a boolean array marking which rows are synthetic. The synthetic rows carry area names starting `synthetic-`, which `split.split_by_area` never sees because the split runs on the ORGANIC dataset before the join.
- `covered_unseen(table_organic, table_mixed, test_keys)` takes the class table built from organic TRAIN only, the class table built from organic plus the mixed synthetic rows, and the list of `data.row_key` tuples of the held-out test rows; it returns a mapping with these three keys: `classes` (distinct test class keys present in the mixed table but absent from the organic table), `rows` (held-out rows whose class is such a key) and `unseen_total_rows` (held-out rows whose class is absent from the organic table). That is "how many unseen_in_train classes synthetic covered".
- `compare(org_rep, mix_rep)` takes two `metrics.evaluate` reports for the SAME test rows and returns a plain mapping with the overall, weighted overall, macro and coarse of each report side by side and the delta (mixed minus organic). `format_text` renders it as a short table whose header names the two columns `organic-only` and `with-synthetic`. The `with-synthetic` column is always labelled as trained-on-synthetic and measured on organic held-out rows.
- Nothing here ever scores a synthetic row, and nothing here chooses a model: `compare` reports, it does not pick a winner and never writes a "better" flag.

### 4.4 `tools/vision_synth.py`

`uv run --frozen python tools/vision_synth.py --game pokemon-red --rom "<path>" [--root runs/vision/pokemon-red/synthetic] [--dry-run]`. The ROM path comes from the argument only; the tool reads the bytes and never prints the path or where the file came from. It refuses a `--root` that is not inside a `runs` folder under the current directory (copy the `out_in_runs(out, cwd)` rule of `tools/vision_record.py`: resolve the path, it must be under the current directory's `runs`; exit code 2 with a message otherwise). It builds `all_crops(rom, tables)` (with `tables_from_rom` only when the dependency is present, else None), writes the store, and prints counts per kind, per tileset, per palette, how many crops had a semantic label and how many were skipped by the byte cap. `--dry-run` counts and writes nothing. Put the work in functions so tests call them without a file; `main(argv=None)` stays thin and the tool prints "synthetic data: local, gitignored, never published".

### 4.5 `data.concat` (the only edit to `src/pokeagent/vision_model/data.py`)

`def concat(a: Dataset, b: Dataset) -> Dataset:` returns a new `Dataset` with every column joined (`np.concatenate`), `a` rows first. If the semantic column from the dependency exists on both, join it; on exactly one, set it to None. Existing fields, dtypes and behaviour are untouched; the existing data tests pass unchanged.

### 4.6 `tools/vision_train.py` (minimal)

Add `--synthetic-share` (float, default 0, `type=float`). With 0 (the default) the tool's behaviour, output and `report.json` are EXACTLY as today, and a test asserts `synthetic_mix.combine` is never called. Above 0:

1. The area split, the leak drop, `assert_disjoint` and the held-out test rows are computed on the ORGANIC dataset exactly as today. The held-out scoring set is organic-only, always.
2. Load the set with `synthetic_store.load_synthetic(root / "synthetic")`; when the folder is missing print "no synthetic set: run tools/vision_synth.py first" to stderr and return 2.
3. Clamp the share with `capped_share` (print "share clamped to <cap>" when it was above the cap), choose `mix_indices`, `combine`, and add the chosen synthetic row positions to the TRAIN index list only. The test index list is untouched.
4. Train and score TWICE on the same test rows: the organic-only run exactly as today, and the with-synthetic run (the class table built from the mixed train rows). Use the time budget `--max-seconds` for each. Both are evaluated with `metrics.evaluate` against the same `y_true` encoding (the full table must contain every class of the mixed table so a class synthetic added is scored, not dropped).
5. Print `synthetic_mix.format_text(compare(...))` and the `covered_unseen` numbers (classes and rows), and add one key `synthetic` to `report.json` with the share used, the cap, the counts of synthetic rows trained on, the compare mapping and the covered-unseen mapping, plus a `provenance` key stating that the held-out rows are organic only. Write the with-synthetic weights to `runs/vision_models/<game>-synthetic/` (a runtime output) so the organic-only model is never overwritten.

If the torch import fails, behave exactly as today (print the message, return 2) but only AFTER the template baseline; the template baseline is organic-only and unchanged by this directive.

### 4.7 The organic proof step (Claude's, after merge; say so in the Report)

A synthetic result counts only after an organic check: (a) the with-synthetic model's score on the organic held-out rows (this directive prints it) must not be lower than the organic-only model's on the same rows, and (b) a sample of synthetic crops is compared against organic crops of the same tile id (mean colour per shade) to confirm the greys match what the emulator renders. Devin cannot do (b), there is no ROM and no `runs/` in the worktree. Never promote a vision model, never record a KNOWLEDGE fact, and never change a default on a synthetic number alone.

## 5. What NOT to do

- Do not change `metrics.evaluate`, `split.py`, `net.py`, `template.py`, or the held-out split rule. Evaluation stays organic-only and area-held-out. Do not add the synthetic set to the test side, to any "unseen" count as if it were held out, or to any threshold decision.
- Do not wire `--labels semantic` or edit the branches of the other two vision directives; do not change `tools/vision_train.py` beyond section 4.6.
- Do not add a horizontal-flip augmentation. Do not invent palette colours, scenery, or tiles the ROM does not hold.
- Do not run an emulator, open a window, read a ROM or `runs/` in tests (tests build synthetic `bytearray` ROMs: write tile graphics bytes at the offsets `load_tileset` reads, the way `tests/test_atlas_rom.py` builds its fixtures; read that file for the style). ROM access is only via bytes passed in; no function in the new modules takes a path except the tool's argument and the store root.
- Do not commit any generated image, any ROM-derived data or any fixture holding real game bytes. Do not state where any game copy came from, in code, comments, docs, commit messages or the report.
- Do not add a dependency. PIL and numpy are already used by the vision package.

## 6. Verification (exact commands)

```
uv run --frozen pytest -q tests/test_vision_synthetic.py tests/test_vision_synthetic_store.py tests/test_vision_synthetic_mix.py tests/test_vision_synth_tool.py tests/test_vision_train_synthetic.py
```
Expected: all pass (torch-dependent cases skip, like the existing net tests).

```
uv run --frozen pytest -q tests/test_vision_dataset.py tests/test_vision_model_data.py tests/test_vision_model_split.py tests/test_vision_store.py tests/test_vision_model_metrics.py tests/test_atlas_rom.py tests/test_vision_sources.py
```
Expected: no new failures. Claude ran this exact command on main while writing the directive; the tail was `22 passed, 2 skipped, 1 warning`.

```
git diff --stat origin/main -- src/pokeagent tools docs
```
Expected: the files in Scope only.

## 7. Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command. Never bare `python`.
- Branch only (`directive/pokeagent-vision-synthetic-crops-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.
- Synthetic data may train, test and drill but never decides truth: never scored on (evaluation is always organic held-out data), never a checkpoint start, chain best, KNOWLEDGE fact or shared-memory veto without organic confirmation. Every synthetic record carries a provenance tag. Reports show organic versus synthetic side by side. The synthetic share of any training mix is capped by the config constant `SYNTHETIC_SHARE_CAP`. ROM-derived data stays local and gitignored, never published. Never state where a game copy came from.
- Tests never open a window.

## 8. Completion criteria

- [ ] Every tile id below `TILE_COUNT` of every readable tileset, and every frame of every readable sprite picture, is rendered at each palette, each of the 9 shifts and each of the 3 brightness gains, with no horizontal-flip augmentation and the plain crop first. <!-- test: tests/test_vision_synthetic.py -->
- [ ] A tileset or sprite entry that cannot be read is skipped without failing the call; the output is deterministic for the same bytes. <!-- test: tests/test_vision_synthetic.py -->
- [ ] The specific label of a synthetic crop equals the class key an organic crop of the same tile or sprite gets (tile: bank is the tileset id; sprite: bank -1), and the semantic label is set only when the dependency is present. <!-- test: tests/test_vision_synthetic.py -->
- [ ] The store writes `provenance` synthetic on every row and in `meta.json`, is byte-identical on a rerun, loads through `data.load_dataset`, and `load_synthetic` refuses a root that is not marked synthetic. <!-- test: tests/test_vision_synthetic_store.py -->
- [ ] `capped_share` never exceeds the constant; `mix_indices` gives the requested fraction, is seeded, and adds the classes missing from organic train first; `covered_unseen` and `compare` report as specified and never pick a winner. <!-- test: tests/test_vision_synthetic_mix.py -->
- [ ] The tool refuses a root outside `runs`, never prints the ROM path, and `--dry-run` writes nothing. <!-- test: tests/test_vision_synth_tool.py -->
- [ ] With `--synthetic-share` 0 the training tool's output and report are unchanged and the mix code is not called; above 0 the synthetic rows reach TRAIN only, the held-out rows and the split are organic-only, and both results print side by side. <!-- test: tests/test_vision_train_synthetic.py -->
- [ ] The existing vision test files in section 6 pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## 9. Report

Diff stat, test tails, the constants and their values (`SYNTHETIC_SHARE_CAP`, shifts, brightness, palette count), whether the semantic dependency was present, and the counts the dry-run tool prints on a synthetic bytearray fixture. Then the steps Claude runs afterwards with the ROM and the real `runs/` (Devin cannot): `uv run --frozen python tools/vision_synth.py --game pokemon-red --rom <path>`, then `uv run --frozen python tools/vision_train.py --game pokemon-red --threads 4 --max-seconds 300 --synthetic-share 0.3`, read the organic-only versus with-synthetic table and the covered-unseen counts, and do the organic proof step in section 4.7 before anyone trusts the number.

## Forbidden Actions

- ROMs, extracted game art, save states, rendered synthetic crops and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The post-merge ROM steps in the Report section, run by Claude. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
