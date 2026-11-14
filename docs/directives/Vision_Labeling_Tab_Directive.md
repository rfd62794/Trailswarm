# PokeAgent: vision labeling tab - a keyboard-first native Dear PyGui tab that asks Robert only about the crops the game data cannot decide or the model is sure about and wrong, and feeds his answers back as labels

**Depends on (all three merged to main; if any is missing from your worktree, stop and write that in the Status row, do not rebuild it):**
1. `Vision_Semantic_Labels_Directive.md` (adds `SEMANTIC`, `Dataset.semantic`, `vision_model/semantic.py` <!-- new: src/pokeagent/vision_model/semantic.py -->, `semantic_view.py` <!-- new: src/pokeagent/vision_model/semantic_view.py -->, the `semantic` field in `samples.jsonl`).
2. `Vision_Error_Triage_Directive.md` (adds `vision_model/triage.py` <!-- new: src/pokeagent/vision_model/triage.py -->, `report["triage"]["confident_wrong"]`).
3. PR #268 (`feat/vision-view`: the native viewer `vision_model/view*.py`, `tools/vision_view.py`).

**Read first:** `docs/research/labeling-systems-standards-2026-11-14.md` <!-- new: docs/research/labeling-systems-standards-2026-11-14.md --> (this PR). The ranking below is its recommendations 1-5.

## Why this exists

Robert, 2026-11-14, approved building a labeling tool. The cheap vision model scores 2.2% (net) and 9.6% (template) on held-out maps 101/64/66 because labels are tile-id@tileset; 573 of 1287 test rows are classes never seen in training (`Vision_Error_Triage_Directive.md`). The semantic-labels directive derives walkable/solid/grass/counter/ledge/npc/item/player from ROM tables, but water, doors, signs and trees are NOT derivable from repo data, so those tile ids land in `other`. Only a human can name them, and Robert has ~15 minutes at a time. The research shows the standard answer: ask only what programmatic labels cannot decide (Snorkel), order by what matters most (active learning, Settles 2009), one key per answer (Prodigy, CVAT), and label once per unique image because our tiles repeat massively (`count` in `samples.jsonl`). So one keypress on an image id must label every row that shares that id.

Constraints: native Dear PyGui only (no web view, no upload); crops and labels are ROM-derived and stay under gitignored `runs/` (`.gitignore` already has `runs/`); tests open no window and send no input.

## Facts pasted from main (the worktree cannot be searched)

`pokeagent.vision.dataset` (main, `src/pokeagent/vision/dataset.py`):
```
iter_samples(root) -> Iterator[dict]   # one row per unique (kind, label, area, image)
load_image(root, id) -> np.ndarray     # (h, w, 3) uint8 crop
iter_thumbs(root) -> Iterator[dict]    # thumbs.jsonl rows: {"id", "area", "cell", ...}
load_thumb(root, id) -> np.ndarray     # (72, 80) uint8 greyscale half-size frame
```
A `samples.jsonl` row: `{"id","kind":"tile"|"sprite","label","coarse","area":"map-0","region","x","y","w","h","count","bank"}`; after the semantic directive also `"semantic": <member of SEMANTIC>` appended last. The same `id` may appear in several rows (different area or label); an id is one image.

`pokeagent.vision_model.data` (main, 88 lines; the semantic directive adds `semantic` as a last `Dataset` field):
```
@dataclass(frozen=True) class Dataset: images, label, coarse, area, kind, bank, weight, w, h, ids   # + semantic (semantic directive)
    def select(self, idx) -> "Dataset"
def load_dataset(root, kinds=KINDS) -> Dataset
```
`SEMANTIC = ("walkable","solid","grass","counter","ledge","npc","item","player","other")` (semantic directive; index = class id). `semantic_view.class_name((kind, bank, idx)) -> SEMANTIC[idx]`.

Triage (triage directive): `report["triage"]["confident_wrong"]` is a list of `{"id": str, "true": name, "pred": name, "confidence": float, "bucket": str}` sorted by confidence descending, length `top_n` (default 20).

Viewer, from `origin/feat/vision-view` (PR #268, NOT on main yet; marked as such):
```
# src/pokeagent/vision_model/view_window.py   (from feat/vision-view)
def run(panels, title: str = "Vision viewer") -> int          # opens the window; one `with dpg.tab_bar():` holding five dpg.tab(label=...)
def _tex(dpg, img, tag: str) -> tuple[int, int]               # dpg.add_static_texture(w, h, flat, tag=tag, parent="vv_tex")
# src/pokeagent/vision_model/view_draw.py
def up(arr, k) -> Image.Image                                  # nearest-neighbour k-times upscale
def cell(img, size, border=None) -> Image.Image
def banner(width, text, h=16) -> Image.Image
def to_rgba_floats(img) -> tuple[int, int, np.ndarray]        # data a Dear PyGui static texture takes
# src/pokeagent/vision_model/view_frames.py
def find_boxes(thumb, crops: dict) -> list                    # crops: row -> (kind, crop array); returns [(x, y, w, h, row)] in frame px
def overlay(thumb, boxes, colour_of, fill: bool, k: int = 4) -> Image.Image
# src/pokeagent/vision_model/view.py
MAX_THUMBS_PER_AREA = 40 ; class Panels (frames, gallery, confusions, ..., numbers) ; def build(root, model_dir, frames=6) -> Panels
# tools/vision_view.py   main(argv=None) -> int ; parse_args has --game --root --model --out --frames --png-only
```
`dearpygui>=2.0` is already a core dependency in `pyproject.toml`. Python is 3.12 (`uv run --frozen python --version` prints `Python 3.12.12`).

## Scope (in this order; every module under its line limit)

1. `src/pokeagent/vision_model/labels_human.py` <!-- new: src/pokeagent/vision_model/labels_human.py --> - the append-only store. Under 110 lines.
2. `src/pokeagent/vision_model/label_queue.py` <!-- new: src/pokeagent/vision_model/label_queue.py --> - the pure queue builder. Under 100 lines.
3. `src/pokeagent/vision_model/label_session.py` <!-- new: src/pokeagent/vision_model/label_session.py --> - cursor, undo, skip, unsure, progress, timing; no Dear PyGui. Under 110 lines.
4. `src/pokeagent/vision_model/label_context.py` <!-- new: src/pokeagent/vision_model/label_context.py --> - the large crop and the frame-context picture, Pillow only. Under 100 lines.
5. `src/pokeagent/vision_model/label_keys.py` <!-- new: src/pokeagent/vision_model/label_keys.py --> - key name to action. Under 50 lines.
6. `src/pokeagent/vision_model/label_tab.py` <!-- new: src/pokeagent/vision_model/label_tab.py --> - the Dear PyGui tab; `dearpygui` imported inside functions only. Under 150 lines.
7. `src/pokeagent/vision_model/human_override.py` <!-- new: src/pokeagent/vision_model/human_override.py --> - apply human labels to a `Dataset`. Under 70 lines.
8. `src/pokeagent/vision_model/data.py` - `Dataset` gains a last optional field `source`; minimal edit.
9. `src/pokeagent/vision_model/semantic_view.py` - `class_name` indexes `HUMAN_CLASSES` instead of `SEMANTIC` (one line; the first nine entries are identical).
10. `src/pokeagent/vision_model/view_window.py` (from PR #268) - `run(panels, title="Vision viewer", label_session=None)`: when a session is given, add the labeling tab by calling `label_tab.add_tab(dpg, label_session, _tex)`. Minimal edit.
11. `tools/vision_view.py` (from PR #268) - `--label` flag that builds the queue and session and passes it to `run`. Minimal edit.
12. `tools/vision_train.py` - `--human` flag: apply human labels before the split. Minimal edit; stays under 150 lines.
13. `docs/KNOWLEDGE.md` - three sentences under the "Sprite model" paragraph.
14. Tests: `tests/test_vision_labels_human.py`, `tests/test_vision_label_queue.py`, `tests/test_vision_label_session.py`, `tests/test_vision_label_context.py`, `tests/test_vision_label_keys.py`, `tests/test_vision_human_override.py`. <!-- new: tests/test_vision_labels_human.py --> <!-- new: tests/test_vision_label_queue.py --> <!-- new: tests/test_vision_label_session.py --> <!-- new: tests/test_vision_label_context.py --> <!-- new: tests/test_vision_label_keys.py --> <!-- new: tests/test_vision_human_override.py -->

## The work

### labels_human.py: the store (recommendation 1)

```
HUMAN_EXTRA = ("water", "door", "sign", "tree")
HUMAN_CLASSES = SEMANTIC + HUMAN_EXTRA          # SEMANTIC from semantic.py; first nine ids identical, so existing semantic ids stay valid
def append(path, image_id, label, *, session, secs, action="label", now=None) -> dict
def load(path) -> dict[str, dict]               # image id -> effective record
def out_in_runs(path, cwd=None) -> bool         # the path must resolve under <cwd>/runs; same rule as tools/vision_record.py
```
`labels_human.jsonl` lives at `runs/vision/<game>/labels_human.jsonl`. One JSON object per line, appended with `open("a")` and one `write` of `json.dumps(rec) + "\n"`; never rewritten, never sorted. Record: `{"id", "action": "label"|"unsure"|"undo", "label": <member of HUMAN_CLASSES or null>, "t": <UTC ISO string>, "session": <str>, "secs": <float seconds spent on this item>}`. `append` raises `ValueError` for an unknown label on `action="label"`, for a `label` on `unsure`/`undo`, and `PermissionError` if `out_in_runs` is false. `load` replays the file in order with a per-id stack: `label`/`unsure` pushes, `undo` pops (an undo with an empty stack is ignored); the effective record is the top of the stack, an id with an empty stack is absent. A half-written last line is skipped, not fatal (same behaviour as `vision/dataset._iter_jsonl`). Propagation is by id alone: the store has one entry per image id and `human_override` applies it to every row with that id.

### label_queue.py: priority, deduped by image id (recommendation 2)

```
def build_queue(rows, triage_wrong=(), suspects=(), labelled=frozenset(), limit=None) -> list[dict]
```
`rows` are `samples.jsonl` dicts that have a `semantic` key (raise `ValueError("no semantic labels: run tools/vision_relabel.py first")` otherwise); `triage_wrong` is `report["triage"]["confident_wrong"]`; `suspects` is a list of image ids (empty for now, the confident-learning list will feed it later); `labelled` is the set of ids in `labels_human.load(...)`. Each queue item: `{"id", "tier", "count", "guess", "area", "kind", "rows"}` where `count` is the SUM of `count` over every row sharing the id, `rows` is the number of such rows, `area` the area of the highest-count row, and `guess` is the triage `pred` when it is in `HUMAN_CLASSES`, else the row's `semantic` when it is not `"other"`, else `None`.
Tiers, first match wins per id: 0 = a TILE row whose `semantic` is `"other"` (the game data could not decide it); 1 = id appears in `triage_wrong`; 2 = id appears in `suspects`. Sprite rows and rows already decided by the game data are not asked about unless they appear in tier 1 or 2. Ids in `labelled` are excluded (including ids marked `unsure`; Robert reviews those separately). Sort by `(tier, -count, id)`; `limit` cuts. Pure: no files, no torch, no numpy needed.

### label_session.py: state, no window (recommendation 3 and 5)

```
class Session:
    def __init__(self, queue, path, session_id, clock=time.monotonic, now=...)
    def current(self) -> dict | None            # the item under the cursor, None when the queue is done
    def label(self, cls) -> None                # appends action=label, advances
    def accept_guess(self) -> bool              # label(current.guess); False and no write when guess is None
    def unsure(self) -> None                    # appends action=unsure, advances
    def skip(self) -> None                      # moves the item to the END of this session's queue; writes nothing
    def undo(self) -> bool                      # appends action=undo for the last written id, puts that item back at the cursor; False if nothing to undo
    def progress(self) -> dict                  # {"done": n, "left": n, "rows_covered": sum of count and rows over labelled ids, "elapsed": s, "mean_secs": s per label}
```
`secs` on each record is the clock time since the item was shown. The clock is injectable so tests control time. The session never reads or writes outside `path`.

### label_keys.py

```
KEYS = {"1": "walkable", "2": "solid", "3": "grass", "4": "counter", "5": "ledge", "6": "npc", "7": "item", "8": "player", "9": "other",
        "W": "water", "D": "door", "I": "sign", "T": "tree"}
SPECIAL = {"U": "undo", "S": "skip", "?": "unsure", "ENTER": "accept"}
def action_for(key: str) -> tuple[str, str | None] | None   # ("label", "water") | ("undo", None) | None for an unmapped key
```
Case-insensitive on letters; `"/"` is accepted for `?` (no shift needed). Every value in `KEYS` is a member of `HUMAN_CLASSES`; a test asserts that and that no key appears in both maps.

### label_context.py: crop large plus frame context

```
def crop_picture(crop: np.ndarray, k: int = 16) -> Image.Image          # nearest-neighbour via view_draw.up
def context_picture(root, item, crop, k=4) -> Image.Image | None        # the thumbnail of item["area"] with the crop's box outlined (view_frames.find_boxes + overlay); None when no thumbnail of that area contains it
```
Use `iter_thumbs` rows of the item's area (at most `MAX_THUMBS_PER_AREA`), `find_boxes(thumb, {0: (item["kind"], crop)})`, and `overlay(thumb, boxes, lambda r: (255, 230, 0), False, k)`. When nothing matches return `None` (the tab then shows the crop alone; do not hunt for another frame).

### label_tab.py: the tab (recommendations 3-5)

`add_tab(dpg, session, tex)` adds one `dpg.tab(label="Label")` to the current tab bar: the large crop, the context picture, a line `tile id/label, area, count rows covered by this key`, the guess, the class legend (`1 walkable ... 9 other, W water, D door, I sign, T tree, Enter accept guess, U undo, S skip, ? unsure`), and a progress line (`done`, `left`, `rows covered`, `elapsed`, `mean secs per label`). Keys are bound with `dpg.handler_registry()` + `dpg.add_key_press_handler` for each key in `KEYS`/`SPECIAL`, calling the session then refreshing the textures with `tex`. When the queue is empty show "Nothing left to ask." Keep refresh logic in one small function. This module is the one piece no test calls (it opens a window); its pure parts live in the modules above.

### human_override.py and the training path (recommendation 1)

```
def apply_human(ds: Dataset, human: dict) -> Dataset
```
Returns `dataclasses.replace(ds, semantic=..., source=...)`: for every row whose `ds.ids[i]` is in `human` with `action == "label"` set `semantic[i] = HUMAN_CLASSES.index(label)` and `source[i] = "human"`; every other row keeps its semantic id and gets `source[i] = "rom"`. `unsure` records are ignored. Raises `ValueError` if `ds.semantic is None`. `Dataset.source` is `np.ndarray | None` of `<U5` strings, default `None`, carried through `select` (`None` stays `None`). `semantic` is `int8` and HUMAN_CLASSES has 13 entries, so it fits. `tools/vision_train.py --human` loads `labels_human.load(root / "labels_human.jsonl")`, applies `apply_human` before `semantic_view.as_semantic`, and prints one line `human labels: <n> ids -> <m> rows (<p>% of rows)`. Without `--human` nothing changes. Human labels apply to train and held-out rows alike (a corrected held-out label is a better test); the leak check by image id is untouched.

### Viewer wiring

`vision_view.py --label` loads `samples.jsonl` rows, `report.json`, `labels_human.load`, calls `build_queue(rows, report.get("triage", {}).get("confident_wrong", []), (), set(human))`, builds a `Session` with a fresh `session_id` (`time.strftime("%Y%m%dT%H%M%S")`), and passes it to `view_window.run`. It refuses a non-`runs` path through `labels_human.out_in_runs` with exit code 2. Without `--label` the viewer behaves exactly as in PR #268.

## What NOT to do

- No web view, no browser, no server, no upload, no network call, no hosted tool, no crowdsourcing or consensus machinery, no second-annotator or agreement code.
- Do not build a tool for classes the game data already decides (walkable, solid, grass, counter, ledge, npc, item, player rows are asked about only when triage lists them).
- Do not rewrite or sort `labels_human.jsonl` in place; it is append-only. Do not delete it. Do not store pixels in it.
- Do not change `src/pokeagent/vision/`, `emulator.py`, `cli.py`, `roms/`, `baselines/`, `triage.py`, `semantic.py`, `semantic_rom.py`, any other viewer file than the two named in Scope, or any Mario or Pokemon tool under `tools/` other than the three named.
- Do not import `torch` or `dearpygui` at module level anywhere; `dearpygui` only inside `label_tab.add_tab` and the viewer's existing `run`.
- Do not read `runs/`, `roms/` or `baselines/` in any test; no test needs a ROM, a dataset, a window or a key press. Tests build rows and arrays in memory and use `tmp_path` (name it `runs` inside `tmp_path` where `out_in_runs` matters).
- Do not add dependencies; do not run `uv lock`, `uv sync`, `pip`, or any install or download. Do not commit any dataset, label file, crop, weights or report. No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Do not state where any game copy came from, in code, comments, docs, the report or commit messages.

## Verification (exact commands; Claude ran the baseline below on origin/main and `uv run python --version` prints `Python 3.12.12`; do not run a bare version command)

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_vision_labels_human.py tests/test_vision_label_queue.py tests/test_vision_label_session.py tests/test_vision_label_context.py tests/test_vision_label_keys.py tests/test_vision_human_override.py
```
Expected: all pass.

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_vision_model_data.py tests/test_vision_model_split.py tests/test_vision_model_template.py tests/test_vision_model_metrics.py tests/test_vision_model_net.py tests/test_vision_model_bench.py tests/test_vision_model_imports.py tests/test_vision_dataset.py
```
Expected (Claude ran this on origin/main, before the semantic and triage directives, and got `16 passed, 6 skipped`): the passed count may only grow; skipped may only be torch tests.

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_vision_view.py
```
Expected: the viewer tests from PR #268 still pass (this file exists once #268 is on main).

```
uv run --frozen pytest -q -p no:cacheprovider
```
Expected: no new failures. Main's full suite at Claude's check: `2984 passed, 63 skipped`; the count grows with the merged dependencies and your tests.

```
git diff --stat origin/main -- src/pokeagent tools pyproject.toml
```
Expected: only the new `label_*.py`, `labels_human.py`, `human_override.py` under `src/pokeagent/vision_model/`, the minimal edits to `data.py`, `semantic_view.py`, `view_window.py`, `tools/vision_view.py`, `tools/vision_train.py`. `pyproject.toml` and `uv.lock` unchanged.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-vision-labeling-tab-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and line counts in the Report.

## Completion criteria

- [ ] `labels_human.append`/`load` are append-only, replay `label`, `unsure` and `undo` per id with a stack, ignore an empty-stack undo and a half-written last line, reject an unknown label and any path outside a `runs` directory. <!-- test: tests/test_vision_labels_human.py -->
- [ ] `build_queue` returns one item per image id with `count` summed over the rows sharing it, orders by `(tier, -count, id)` with tiers tile-`other` then triage then suspects, excludes labelled and `unsure` ids, picks the documented `guess`, honours `limit`, and raises `ValueError` without `semantic`. <!-- test: tests/test_vision_label_queue.py -->
- [ ] `Session` with an injected clock: `label` and `accept_guess` write one record with the right `secs`, `skip` writes nothing and moves the item last, `unsure` writes, `undo` restores the previous item and writes an `undo` record, `progress` reports done, left, rows covered, elapsed and mean seconds. <!-- test: tests/test_vision_label_session.py -->
- [ ] `action_for` maps every key in `KEYS` and `SPECIAL`, is case-insensitive, accepts `/` for `?`, returns `None` for an unmapped key, and every `KEYS` value is in `HUMAN_CLASSES`. <!-- test: tests/test_vision_label_keys.py -->
- [ ] `crop_picture` scales by `k`; `context_picture` returns an image with the box outlined for a synthetic thumbnail built with `pokeagent.vision.crops.thumb` and `None` when no thumbnail matches (synthetic thumbnails under `tmp_path`). <!-- test: tests/test_vision_label_context.py -->
- [ ] `apply_human` sets `semantic` and `source="human"` on every row sharing a labelled id (propagation), leaves others `"rom"`, ignores `unsure`, keeps the leak check by id valid, and raises without `semantic`; `Dataset.select` carries `source`. <!-- test: tests/test_vision_human_override.py -->
- [ ] A subprocess with a stub `dearpygui` and `torch` that raise `ImportError` can import every new module. <!-- test: tests/test_vision_label_keys.py -->
- [ ] Every new file is under its stated line limit; `tools/vision_train.py` stays under 150 lines; no new dependency.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails (and which tests skipped), line counts per new file, and the exact on-disk record shape of one `labels_human.jsonl` line. Then the checks Claude runs afterwards on the laptop (Claude's lane; Devin cannot do them):

1. With the real dataset: `uv run python tools/vision_view.py --game pokemon-red --label`, watch the tab open, press `1`, `U`, `S`, `?` and `Enter` once each, and confirm `runs/vision/pokemon-red/labels_human.jsonl` gained the matching lines and the progress line moved.
2. Run `uv run python tools/vision_train.py --game pokemon-red --labels semantic --human` and read the `human labels: ...` line and the held-out semantic accuracy against the run without `--human`.
3. Time one 15 minute session: labels per minute, rows covered per label (the `count` payoff), and whether the context frame was found for most crops.
4. Confirm `git status` shows no label file, crop or report outside gitignored paths.

## Forbidden Actions

- ROMs, extracted game art, datasets, trained weights, human label files and anything derived from them are ROM-derived: they stay local and gitignored. Never commit them, never add them to a fixture, never publish or upload them.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not edit `src/pokeagent/vision/`, `src/pokeagent/emulator.py`, `src/pokeagent/cli.py`, `roms/`, `baselines/`, or any Mario or Pokemon tool under `tools/` other than the three named in Scope.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a window or send input in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- DO NOT DISPATCH before all three dependencies are merged to main: `Vision_Semantic_Labels_Directive.md` built and merged, `Vision_Error_Triage_Directive.md` built and merged, and viewer PR #268 merged. Check with `git grep -n "SEMANTIC =" -- src/pokeagent/vision_model/semantic.py`, `git grep -n "def triage" -- src/pokeagent/vision_model/triage.py` and `git cat-file -e origin/main:src/pokeagent/vision_model/view_window.py`. If any finds nothing at the start of the run, stop and write that in the Status row.
- The real-data and window checks in the Report section, run by Claude (or Robert) after the verify lane passes. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
