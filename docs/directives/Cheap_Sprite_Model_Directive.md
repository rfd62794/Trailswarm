# PokeAgent: Cheap sprite model - a tiny CPU-trainable classifier that recognises sprite classes from pixels alone, scored against a nearest-template baseline on held-out maps

## Why this exists

Robert, 2026-11-08, approved: use game RAM as free labels to train cheap local models. Directive 1 (`Vision_Label_Recorder_Directive.md`) writes a local dataset of sprite and tile crops labelled from RAM and OAM. This directive trains a small model on it. The point is a perception model that is cheap enough for a CPU: given a crop of pixels with no RAM access, say what it is (specific class) and whether it is an enemy, NPC, item, player or terrain (coarse class). Today the agent reads RAM for all of this; a pixels-only model is what would let a later agent perceive a game whose RAM map nobody has written yet.

**Base requirement:** this run starts from a main that contains directive 1 (the package `src/pokeagent/vision/`). If `git grep -n "def iter_samples" -- src/pokeagent/vision/dataset.py` finds nothing at the start of the run, stop and write that in the Status row; do not recreate that package.

The dataset reader directive 1 provides, pasted because the worktree cannot be searched and the dataset itself is not in the worktree (it is gitignored and ROM-derived):

```
from pokeagent.vision.dataset import load_meta, iter_samples, load_image, iter_thumbs, iter_positions
iter_samples(root) -> iterator of dict rows from <root>/samples.jsonl:
   {"id":"<sha1>","kind":"sprite"|"tile","label":<int>,"coarse":"enemy"|"npc"|"item"|"player"|"terrain"|"other",
    "area":"<string>","region":"r<0-2>c<0-2>","x":int,"y":int,"w":int,"h":int,"count":int,"bank":int|None}
load_image(root, id) -> np.ndarray (h, w, 3) uint8     # crop from <root>/images/<hh>/<id>.png
```
`root` is `runs/vision/<game>/` (`pokemon-red` or `mario-land`). Sprite crops are 16x16 (Red) or 8x8 / 8x16 (Mario); tile crops are 8x8. `area` is `map-<id>` for Red and `<world>-<level>` for Mario. The Mario `coarse` classes are provisional (player vs enemy by position); the specific tile-id label is exact. A row exists once per distinct image per `(kind, label, area)`; `count` says how often it was seen.

What exists today in the repo: numpy, Pillow and pytest only. There is no torch. Python is 3.12 (`uv run python --version` prints `Python 3.12.12`). `pyproject.toml` has `[dependency-groups] dev = ["pytest>=8"]`.

## Scope (in this order)

1. `src/pokeagent/vision_model/__init__.py` <!-- new: src/pokeagent/vision_model/__init__.py --> - one-line docstring; imports nothing heavy.
2. `src/pokeagent/vision_model/data.py` <!-- new: src/pokeagent/vision_model/data.py --> - turn samples into arrays: pad every crop to 16x16, one array of images and arrays of label, coarse and area. Pure numpy. Under 100 lines.
3. `src/pokeagent/vision_model/split.py` <!-- new: src/pokeagent/vision_model/split.py --> - the split by area. Pure. Under 70 lines.
4. `src/pokeagent/vision_model/template.py` <!-- new: src/pokeagent/vision_model/template.py --> - the nearest-template baseline. Pure numpy. Under 80 lines.
5. `src/pokeagent/vision_model/metrics.py` <!-- new: src/pokeagent/vision_model/metrics.py --> - per-class accuracy, coarse accuracy, support counts, confusion list, and the report dict. Pure. Under 110 lines.
6. `src/pokeagent/vision_model/net.py` <!-- new: src/pokeagent/vision_model/net.py --> - the torch model and its training loop. Torch imported inside functions only. Under 150 lines.
7. `src/pokeagent/vision_model/bench.py` <!-- new: src/pokeagent/vision_model/bench.py --> - inference timing per crop and per frame. Under 90 lines.
8. `src/pokeagent/vision_model/export.py` <!-- new: src/pokeagent/vision_model/export.py --> - save and load weights plus the label tables under a local models directory. Under 80 lines.
9. `tools/vision_train.py` <!-- new: tools/vision_train.py --> - launcher: train, evaluate, benchmark, write the report. Under 120 lines.
10. `pyproject.toml` - add the optional dependency group (see the work). Do not run `uv lock` or `uv sync`.
11. `.gitignore` - make sure the legal entries exist (see the work).
12. `docs/KNOWLEDGE.md` - a short "Sprite model" paragraph.
13. Tests under `tests/`: `tests/test_vision_model_data.py`, `tests/test_vision_model_split.py`, `tests/test_vision_model_template.py`, `tests/test_vision_model_metrics.py`, `tests/test_vision_model_net.py`, `tests/test_vision_model_bench.py`, `tests/test_vision_model_imports.py`. <!-- new: tests/test_vision_model_data.py --> <!-- new: tests/test_vision_model_split.py --> <!-- new: tests/test_vision_model_template.py --> <!-- new: tests/test_vision_model_metrics.py --> <!-- new: tests/test_vision_model_net.py --> <!-- new: tests/test_vision_model_bench.py --> <!-- new: tests/test_vision_model_imports.py -->

## The work

### Optional dependency, never core

Add to `pyproject.toml` a group `vision = ["torch>=2.3"]` under `[dependency-groups]` and nothing under `[project] dependencies`. Do not run `uv lock`, `uv sync` or any install in this run (the run is non-interactive and cannot fetch). Because `pyproject.toml` then differs from `uv.lock`, EVERY `uv run` in this directive uses `--frozen` (`uv run --frozen pytest ...`), which uses the lock as it is. Claude refreshes the lock and installs the group afterwards (see the Report). No module under `src/pokeagent/` outside `vision_model/net.py`, `bench.py` and `export.py` may import torch, and those three import it only inside functions (`import torch` in a function body), so that `import pokeagent.vision_model` and `import pokeagent.vision_model.net` both succeed without torch. A test proves this by running in a subprocess with torch blocked (see criteria). Torch tests use `pytest.importorskip("torch")` inside the test, so they skip cleanly in this worktree; the numpy parts are fully tested here.

### data.py

`load_dataset(root, kinds=("sprite", "tile")) -> Dataset` where `Dataset` is a frozen dataclass: `images (N,16,16,3) uint8`, `label (N,) int32`, `coarse (N,) int8` (index into `COARSE = ("enemy","npc","item","player","terrain","other")`), `area (N,) <U..>`, `kind (N,) int8`, `bank (N,) int32` (-1 for None), `weight (N,) float32` (the row `count`, capped at 20 so a common image cannot dominate). Crops smaller than 16x16 are placed top-left on a neutral background (the crop's median colour) and the original size is kept in `w`, `h` arrays so a model can see it. A `Dataset.select(mask)` returns a subset. The specific class for training is the pair `(kind, bank, label)` mapped to a dense id by `class_table(dataset) -> dict`; tile classes with `bank` keep the bank in the key because a tile id means different art in different tilesets. Keep tiles and sprites as separate tables (`kinds` argument), since a sprite id and a tile id are unrelated numbers.

### split.py: split by area, never by frame

`split_by_area(areas, test_fraction=0.25, seed=0, min_test_areas=2) -> tuple[set, set]` returns the train area set and the test area set. Rules: sort the distinct areas, shuffle with `random.Random(seed)`, take whole areas into the test set until at least `test_fraction` of the SAMPLES (weighted by row count) are in it and at least `min_test_areas` areas are held out; if fewer than `min_test_areas + 1` areas exist, raise `ValueError("need at least 3 areas to split by area")` rather than fall back to a random split. No sample may appear on both sides (an image id that occurs in a train area AND a test area is removed from the TEST side, because it could be memorised). `assert_disjoint(train_idx, test_idx, dataset)` checks areas and, separately, image ids, and the report records how many test rows were removed for that reason.

### template.py: the baseline to beat

Nearest-template match, no learning beyond averaging: for each class, the template is the mean image of its training crops (per class, 16x16x3 float32); a test crop gets the class with the smallest mean squared difference, over classes of the same kind and, for tiles, the same bank when that bank has templates (else all banks). Also a coarse prediction: coarse of the nearest class. `fit_templates(dataset, idx)` and `predict_templates(templates, images)` are vectorised numpy (one matrix operation over all test crops, not a Python loop per crop). This is the number the network must beat; report it beside the network's.

### metrics.py

`evaluate(pred_label, true_label, pred_coarse, true_coarse, class_names, weight=None) -> dict` returns `{"overall": acc, "macro": mean per-class acc, "coarse": acc, "per_class": {name: {"support": n, "acc": a}}, "coarse_per_class": {...}, "top_confusions": [[true, pred, n], ...up to 10]}`. Classes with zero test support are omitted from `macro`, listed with `support: 0`. A class absent from training but present in the test set counts as an error for any model (report it as `unseen_in_train` count; do not drop it silently, this is the honest generalisation number across maps). Both an unweighted (per distinct image) and a weighted accuracy are reported.

### net.py: the model

- `TinyNet`: three 3x3 conv layers (16, 32, 32 channels) each with ReLU and a 2x2 max pool, global average pool, then two linear heads on the pooled vector: the specific class (`n_classes`) and the coarse class (6). Under 30 000 parameters at `n_classes <= 200`; a test asserts the parameter count. Input is (3,16,16) float32 in 0..1.
- `train(dataset, train_idx, class_table, *, epochs=30, batch=128, lr=2e-3, seed=0, threads=1, max_seconds=300) -> TrainResult`: Adam, loss = cross entropy on the specific head plus 0.5 times cross entropy on the coarse head, sample weights from `weight`, light augmentation that keeps the label true (a one-pixel shift and a brightness jitter of +-10%; NO horizontal flip, since facing matters to a few classes and a flip changes it), a fixed seed (`torch.manual_seed`, `numpy.random.default_rng`), `torch.set_num_threads(threads)`, and a hard wall-clock stop at `max_seconds` (stop at an epoch boundary and say so in the result). CPU only, never CUDA, never downloads anything.
- `predict(model, images, batch=512) -> (label_idx, coarse_idx)`. Deterministic, `torch.no_grad()`.
- The test with torch trains on a synthetic dataset of 4 classes made of distinct small patterns plus noise across 6 synthetic areas and must reach a high held-out accuracy (above 0.9), using under 10 seconds.

### bench.py: measured inference cost

`measure(model, n_crops_per_frame=60, batches=200, threads=1) -> dict` returns `{"ms_per_crop": ..., "ms_per_frame": ..., "threads": ..., "n_crops": ..., "params": ...}`: a frame is a batch of `n_crops_per_frame` 16x16 crops (up to 15 sprites plus a few dozen distinct tiles), timed with `time.perf_counter` after 10 warm-up batches, reporting the median over `batches` batches. It is reported as a measurement with the machine's CPU count, never as a promise; the template baseline gets the same measurement for comparison (`measure_template`). The report includes both.

### export.py

`save(model, class_table, out_dir)` writes `weights.pt` and `classes.json` under `runs/vision_models/<game>/` and refuses any directory that is not inside a `runs` directory under the current working directory. `load(out_dir)` rebuilds the model. These files are ROM-derived and gitignored; nothing in the repo may reference a committed weights file.

### tools/vision_train.py

`uv run --frozen python tools/vision_train.py --game pokemon-red [--root runs/vision/pokemon-red] [--epochs 30] [--seed 0] [--threads 1] [--max-seconds 300] [--kinds sprite,tile]` loads the dataset, splits by area, prints the area split, fits the template baseline and the network on the train side, evaluates both on the held-out areas, benchmarks inference, saves the model and writes `runs/vision_models/<game>/report.json` plus a readable table to stdout: overall, macro, coarse accuracy, per-class accuracy with support, the template baseline next to it, the unseen-in-train count, the removed-for-leak count, ms per crop and per frame, and the parameter count. If torch is not importable the tool trains nothing, prints the template baseline and says exactly `uv sync --group vision` is needed, and exits non-zero. If the dataset directory is missing it says so and exits non-zero.

### Legal and gitignore

Confirm `.gitignore` already has `runs/vision/`, `runs/vision_models/`, `*.pt`, `*.pth`, `*.npz` (directive 1 adds them); add any that are missing. The model and report are ROM-derived and stay local.

## What NOT to do

- Do not change `src/pokeagent/vision/` (directive 1's package), `src/pokeagent/emulator.py`, `cli.py`, the agent, or any Pokemon behaviour. `git diff --stat main -- src/pokeagent` must list only added files under `src/pokeagent/vision_model/`.
- Do not split by random frame or random row anywhere, including in tests and in the tool. Do not tune hyperparameters on the held-out areas; the held-out set is scored once per run.
- Do not add torch (or anything) to `[project] dependencies`, and do not import torch at module level anywhere.
- Do not run `uv lock`, `uv sync`, `pip` or any install or download. Do not use a pretrained model.
- Do not read `runs/`, `roms/` or `baselines/` in tests; no test may need a ROM or a dataset. Tests build datasets in memory or under `tmp_path`.
- Do not commit any dataset, weights, report or image. No window. No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Do not state where any game copy came from.

## Verification (exact commands; Claude confirmed `uv run python --version` prints `Python 3.12.12` in this repo; do not run a bare version command, it is not in the sandbox list)

```
uv run --frozen pytest -q tests/test_vision_model_data.py tests/test_vision_model_split.py tests/test_vision_model_template.py tests/test_vision_model_metrics.py tests/test_vision_model_net.py tests/test_vision_model_bench.py tests/test_vision_model_imports.py
```
Expected: all pass; the torch tests are reported as skipped when torch is absent, and that is acceptable here.

```
git diff --stat main -- src/pokeagent pyproject.toml
```
Expected: only added files under `src/pokeagent/vision_model/` and the one added group in `pyproject.toml`.

```
uv run --frozen pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command, for the reason given in the work.
- Branch only (`directive/pokeagent-cheap-sprite-model-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and line counts in the Report.

## Completion criteria

- [ ] `load_dataset` pads small crops to 16x16, caps `weight` at 20, keeps tile classes keyed by bank, and keeps sprite and tile class tables separate. <!-- test: tests/test_vision_model_data.py -->
- [ ] `split_by_area` is deterministic for a seed, holds out whole areas only, reaches the test fraction, raises `ValueError` with fewer than 3 areas, and removes from the test side any image id that also occurs in a train area; `assert_disjoint` fails on a hand-made overlap. <!-- test: tests/test_vision_model_split.py -->
- [ ] The template baseline classifies a synthetic set of distinct patterns correctly, is vectorised (one call for all test crops), respects the bank for tiles, and returns a coarse class. <!-- test: tests/test_vision_model_template.py -->
- [ ] `evaluate` reports overall, macro, coarse, per-class accuracy with support, the top confusions, and counts a class unseen in training as an error and in `unseen_in_train`. <!-- test: tests/test_vision_model_metrics.py -->
- [ ] With torch present, `TinyNet` has under 30 000 parameters, trains on the synthetic dataset to above 0.9 held-out accuracy in under 10 seconds, is deterministic for a seed, and `export.save` refuses a directory outside `runs`; without torch these tests skip. <!-- test: tests/test_vision_model_net.py -->
- [ ] `bench.measure` returns the documented keys with positive numbers for a stand-in model (with torch) and `measure_template` does the same without torch. <!-- test: tests/test_vision_model_bench.py -->
- [ ] A subprocess with torch import blocked (insert a stub `torch` entry that raises `ImportError` into `sys.modules`, or run with an import hook) can `import pokeagent`, `pokeagent.vision_model`, `pokeagent.vision_model.net`, `.bench` and `.export` without error, and `pyproject.toml` lists torch only in the `vision` group. <!-- test: tests/test_vision_model_imports.py -->
- [ ] Every new file is under its stated line limit, and the tool and tests contain no random-frame split.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails (including which tests skipped for lack of torch), line counts of each new file, and the constants chosen. Then the checks Claude runs afterwards with the ROM and torch (Claude's lane; Devin cannot do them):

1. `uv lock` then `uv sync --group vision` (adds torch), then rerun `tests/test_vision_model_net.py` and `tests/test_vision_model_bench.py` without skips.
2. With the directive 1 dataset recorded from real play, run `tools/vision_train.py` for Pokemon Red and Super Mario Land and read the report: held-out accuracy per class beside the template baseline, the unseen-in-train count, and ms per crop and per frame on this CPU.
3. Check the split really held out whole maps or levels (print the areas), and that no image id crosses sides.
4. Open the ten worst confusions as images and decide whether the labels or the model are at fault.
5. Confirm `git status` shows no weights, report or image outside gitignored paths.

## Forbidden Actions

- ROMs, extracted game art, datasets, trained weights and anything derived from them are ROM-derived: they stay local and gitignored. Never commit them, never add them to a fixture, never publish them.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not edit `src/pokeagent/vision/`, `src/pokeagent/emulator.py`, `src/pokeagent/cli.py`, `roms/`, `baselines/`, or any Mario or Pokemon tool under `tools/`.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a window or send input in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- Directive 1 merged to main before dispatch (or the run branched from a base that contains it).
- The ROM and torch checks in the Report section, run by Claude after the verify lane passes (including `uv lock` and `uv sync --group vision`). Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-cheap-sprite-model-directive |
| Base branch | - |
| Base commit | 15cdb87964ffe90f4e2a5caca7b4ccf66cc9db4c |
| Head commit | c08afe702c360018df5b3de8bd7bd04a0287a012 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-08 13:21 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert: cheap sprite classifier (directive 2 of 3); needs directive 1 merged
- 2026-11-14 00:42 · robert-claude-laptop · Queued → Approved — lint override: vision_model/net.py is a new module this directive creates; its dependency (pokeagent.vision.dataset, directive 1) merged as #251.
- 2026-11-14 01:12 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-cheap-sprite-model-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7CAZPZE0KH1HDKWZJ3ZJAZP
- 2026-11-14 01:23 · dispatcher · launched pid=17064; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-cheap-sprite-model-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (3 declared need(s), repo-scoped only))
- 2026-11-14 01:33 · devin · In progress → Review — Done. Diff stat vs main: 9 files, +498 — only new files under src/pokeagent/vision_model/ plus the added `vision` group line in pyproject.toml (torch>=2.3; nothing in project deps). Focused suite: `uv run --frozen pytest -q tests/test_vision_model_*.py` = 14 passed, 6 skipped (the torch-gated tests: 5 in test_vision_model_net, 1 in test_vision_model_bench — torch absent in worktree, skip expected). Full suite `uv run --frozen pytest -q` = 2884 passed, 61 skipped, 0 failures. Line counts vs limits: data 88/100, split 49/70, template 63/80, metrics 58/110, net 123/150, bench 64/90, export 51/80, tools/vision_train 109/120. Constants: SIZE=16 pad top-left on median colour, MAX_WEIGHT=20, COARSE 6-way, class key (kind,bank,label), split test_fraction .25 seed 0 min_test_areas 2, train epochs 30 batch 128 lr 2e-3 aug +-1px shift + +-10% brightness (no flip), bench 60 crops/frame 200 batches 10 warmup. gitignore already had runs/vision*, *.pt/pth/npz — unchanged. Claude's lane after verify: `uv lock`, `uv sync --group vision`, rerun net/bench tests without skips, run tools/vision_train.py for pokemon-red and mario-land, eyeball worst confusions, confirm git status clean of weights/reports. [origin] spent: devin 10 min est. n/a
- 2026-11-14 02:20 · robert-claude-laptop · Review → Done — note: Merged #258 at 5e97693 (Devin c08afe7 + Claude's uv.lock fix). Reviews APPROVE; cloud GREEN 2909 passed, uv lock --check OK; laptop with ROM 2959 passed, 0 failed. Model not yet trained on real data (needs the laptop-recorded dataset).
<!-- queue:end -->
