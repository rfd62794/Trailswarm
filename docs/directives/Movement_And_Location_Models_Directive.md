# PokeAgent: Movement and location models - NPC movement type and next position, and map or level plus rough position from pixels alone, each beside a simple baseline

## Why this exists

Robert, 2026-11-08, approved: use game RAM as free labels to train cheap local models. Directive 1 (`Vision_Label_Recorder_Directive.md`) records, headless, a local dataset: labelled crops, 80x72 greyscale frame thumbnails with their map or level and position, and a per-frame log of every NPC's position. This directive trains two small models on the thumbnails and the position log:

1. **Movement**: classify an NPC track as stationary, wandering or patrolling, and predict where it will be next. The use is concrete: a patrolling NPC that suddenly stops at the same tile while the model expects it to move is a sign the corridor is blocked, which is what the agent's blocked-path logic currently learns only by walking into it (`src/pokeagent/explorer/memory.py` `observe_npcs` and `anomaly_sprites.py` `wanderer_slots` record only that an NPC "moves": true or false).
2. **Location**: from the screen pixels alone, say which map or level it is and roughly where in it. This is what an agent would need in a game whose RAM map nobody has written.

**Base requirement:** this run starts from a main that contains directive 1 (the package `src/pokeagent/vision/`). If `git grep -n "def iter_positions" -- src/pokeagent/vision/dataset.py` finds nothing at the start of the run, stop and write that in the Status row; do not recreate that package. This directive does NOT depend on directive 2 and must not import `pokeagent.vision_model`.

The dataset reader directive 1 provides, pasted because the worktree cannot be searched and the dataset is gitignored and ROM-derived, so it is not in the worktree:

```
from pokeagent.vision.dataset import load_meta, iter_thumbs, load_thumb, iter_positions
root = runs/vision/<game>/       game = "pokemon-red" | "mario-land"
iter_thumbs(root)   -> dict rows of thumbs.jsonl: {"id":"<sha1>","area":"map-37","cell":"<string>","pos":[x,y],"count":n}
load_thumb(root,id) -> np.ndarray (72, 80) uint8 greyscale
iter_positions(root)-> dict rows of positions.jsonl, one per sampled frame:
   {"f":<frame>,"run":"<run id>","area":"map-37","player":[x,y],"ents":[[ident,label,x,y,move], ...]}
```
`ident` is `slot<i>` for Red NPCs, stable within a run and an area; the movement byte `move` is the raw byte (believed 0xFF = stays, 0xFE = walks; UNVERIFIED, Claude checks it with the ROM). Mario `ident`s are `oam<i>` and are NOT stable between frames, so the movement model is Pokemon Red only and the location model works for both games. Red coordinates are map tiles, `cell` is `f"{x//4},{y//4}"` for Red and `f"{level_progress//128}"` for Mario. Frames are sampled every 8 emulator frames by default; one Red NPC step takes 16 frames, so an NPC mid-walk shows the same tile for two samples.

Python is 3.12 (`uv run python --version` prints `Python 3.12.12`). The repo has numpy, Pillow, pytest; no torch.

## Scope (in this order)

1. `src/pokeagent/vision_motion/__init__.py` <!-- new: src/pokeagent/vision_motion/__init__.py --> - one-line docstring.
2. `src/pokeagent/vision_motion/tracks.py` <!-- new: src/pokeagent/vision_motion/tracks.py --> - group position rows into tracks keyed `(run, area, ident)`, ordered by frame; collapse and dwell helpers. Pure. Under 100 lines.
3. `src/pokeagent/vision_motion/features.py` <!-- new: src/pokeagent/vision_motion/features.py --> - track features (see the work). Pure numpy. Under 90 lines.
4. `src/pokeagent/vision_motion/movement.py` <!-- new: src/pokeagent/vision_motion/movement.py --> - the movement-type labels and the statistical classifier. Under 130 lines.
5. `src/pokeagent/vision_motion/nextpos.py` <!-- new: src/pokeagent/vision_motion/nextpos.py --> - next-position baselines and the statistical (count-table) model. Under 130 lines.
6. `src/pokeagent/vision_motion/nextpos_net.py` <!-- new: src/pokeagent/vision_motion/nextpos_net.py --> - the optional neural next-position model; torch imported inside functions only. Under 120 lines.
7. `src/pokeagent/vision_motion/blocked.py` <!-- new: src/pokeagent/vision_motion/blocked.py --> - the blocked-corridor detector. Under 90 lines.
8. `src/pokeagent/vision_motion/synthetic.py` <!-- new: src/pokeagent/vision_motion/synthetic.py --> - generators for synthetic tracks and rows (stationary, wandering, patrolling, blocked patrol). Pure, seeded. Under 120 lines.
9. `src/pokeagent/vision_motion/split.py` <!-- new: src/pokeagent/vision_motion/split.py --> - area split for tracks, and a held-out-cell split for thumbnails. Pure. Under 110 lines.
10. `src/pokeagent/vision_motion/location_data.py` <!-- new: src/pokeagent/vision_motion/location_data.py --> - load thumbnails into arrays with area and parsed cell. Under 80 lines.
11. `src/pokeagent/vision_motion/location_baseline.py` <!-- new: src/pokeagent/vision_motion/location_baseline.py --> - nearest-thumbnail baseline. Pure numpy. Under 70 lines.
12. `src/pokeagent/vision_motion/location_net.py` <!-- new: src/pokeagent/vision_motion/location_net.py --> - the small CNN on thumbnails; torch inside functions only. Under 140 lines.
13. `src/pokeagent/vision_motion/report.py` <!-- new: src/pokeagent/vision_motion/report.py --> - accuracy helpers and the report dict and table. Pure. Under 110 lines.
14. `tools/motion_train.py` <!-- new: tools/motion_train.py --> - launcher for both models. Under 140 lines.
15. `pyproject.toml` - ensure the optional group (see the work). Do not run `uv lock` or `uv sync`.
16. `.gitignore` - make sure the legal entries exist.
17. `docs/KNOWLEDGE.md` - a short "Movement and location models" paragraph.
18. Tests under `tests/`: `tests/test_motion_tracks.py`, `tests/test_motion_movement.py`, `tests/test_motion_nextpos.py`, `tests/test_motion_blocked.py`, `tests/test_motion_split.py`, `tests/test_motion_location.py`, `tests/test_motion_imports.py`. <!-- new: tests/test_motion_tracks.py --> <!-- new: tests/test_motion_movement.py --> <!-- new: tests/test_motion_nextpos.py --> <!-- new: tests/test_motion_blocked.py --> <!-- new: tests/test_motion_split.py --> <!-- new: tests/test_motion_location.py --> <!-- new: tests/test_motion_imports.py -->

## The work

### Optional dependency, never core

If `pyproject.toml` has no `vision` group under `[dependency-groups]` yet, add `vision = ["torch>=2.3"]` (directive 2 adds the same line; if it is there, leave it alone). Nothing goes under `[project] dependencies`. Do not run `uv lock`, `uv sync` or any install: the run is non-interactive and cannot fetch. Because `pyproject.toml` then differs from `uv.lock`, EVERY `uv run` here uses `--frozen`. Torch is imported only inside function bodies in `nextpos_net.py` and `location_net.py`, so `import pokeagent.vision_motion.location_net` works without torch; torch tests use `pytest.importorskip("torch")` and skip cleanly in this worktree. Every numpy part is fully tested here.

### Split rules (the same rule for both models, applied honestly)

- **Movement and next position: split by area.** `split_tracks_by_area(tracks, test_fraction=0.25, seed=0, min_test_areas=2)` holds out whole maps (weighted by number of tracks) with a seeded shuffle; fewer than 3 areas raises `ValueError("need at least 3 areas to split by area")`, never a fallback to a random split. No random split of frames or tracks anywhere.
- **Location: a classifier cannot name a map it was never shown, so splitting by map is meaningless for the "which map" head.** The split that prevents memorisation here is by position: `split_thumbs_by_cell(rows, test_fraction=0.25, seed=0)` holds out whole `(area, cell)` blocks, so the exact screens near the test position are never in training, and additionally removes from the test side any thumbnail id that also occurs in a train block. The report states this rule in its first line. A second, harder number is also required: hold out one whole area at a time for the "rough position" head only if the game gives the same cell layout across areas (it does not), so do NOT report it; report instead `area_accuracy_by_heldout_cell` and `position_error_by_heldout_cell`. Say in the Report that "which map from an unseen map" is not defined and was not claimed.

### Movement type

Labels (`movement.py`, function `label_track(track) -> str | None`), from RAM, never from the model's own features:
- `move == 255` on every row of the track -> `"stationary"`.
- `move == 254` -> walks. A walking track is `"patrolling"` when its observed tiles are collinear (all on one row or all on one column), it has at least 2 distinct tiles and at least 2 direction reversals; otherwise `"wandering"`. The patrolling/wandering split uses the observed trajectory, so it is an observed label and is weaker than the RAM stationary/walking split: the report must print the stationary-vs-walking accuracy (pure RAM truth) as the headline and the three-way accuracy beside it, and say which is which.
- Any other `move` value, or a track shorter than 6 rows, -> `None` (excluded, counted in the report).

Features (`features.py`) from the first `W = 24` rows of a track only (a classifier must decide early): number of distinct tiles, fraction of rows where the position changed, bounding box width and height, number of reversals, mean dwell (rows per distinct tile), whether the tiles are collinear. The leakage rule: the classifier sees these features only, never `move`, and the collinear/reversal features are computed from the first `W` rows while the patrolling label uses the whole track, so a track whose first window looks stationary but later patrols is a legitimate hard case.

Statistical model (`movement.py`): a decision-rule classifier fitted on the train areas with plain numpy (pick the single threshold per feature that maximises train accuracy for a shallow tree of depth at most 3; no libraries). Also a majority-class baseline. Report held-out accuracy per class with support for both, three-way and stationary-vs-walking.

### Next position

Problem: given the last 4 distinct-or-repeated samples of an NPC, predict its displacement at the sample `H = 2` samples ahead, as one of five classes `stay, up, down, left, right` (any displacement is mapped to the sign of its dominant axis; a diagonal or a jump of more than one tile is excluded and counted). Models:
- `stay` baseline (predict no move).
- `continue` baseline (repeat the last non-zero displacement of the track so far).
- Count-table statistical model (`nextpos.py`): `P(next | last displacement, dwell bucket)` with dwell buckets 0, 1, 2, 3+ samples spent on the current tile, fitted on train areas, with back-off to `P(next | last displacement)` and then to the class prior; Laplace smoothing of 1. Prediction is the argmax.
- Optional neural model (`nextpos_net.py`): a small MLP (two hidden layers of 32) over the one-hot of the last 4 displacements and the dwell bucket; trained with the fixed seed, CPU only.

Metrics for every model: top-1 accuracy over all steps AND over the steps where the truth is not `stay` (the number that matters, since `stay` dominates), plus the per-class table. **Adoption rule, coded in `tools/motion_train.py` and printed:** the neural model is reported as adopted only if its non-stay accuracy beats the count-table model's on the held-out areas by at least 2 percentage points on at least 200 held-out non-stay steps; otherwise print `neural not adopted` and the numbers. If torch is missing the neural model is skipped and that is printed; nothing fails.

### Blocked corridor, on a synthetic fixture

`synthetic.py` builds tracks with a seeded generator: `stationary(n)`, `wandering(n, seed)`, `patrol(n, length, axis, seed, pause=0)`, and `patrol_blocked(n, length, axis, block_at, seed)` which patrols a corridor of `length` tiles and then, from sample `block_at`, stops permanently at the tile before the block. It can also emit rows in the `iter_positions` shape. `blocked.py` has `flag_blocked(track_rows, model, window=6, min_expected_move=0.5) -> int | None`, returning the sample index at which it first flags: over the last `window` samples the count-table model's mean probability of a non-stay next step (given the track so far) is at least `min_expected_move` while the NPC has not changed tile for the whole window. The report block `blocked_corridor` contains, over 100 seeded synthetic tracks of each kind: detection rate on blocked patrols, median detection delay in samples after `block_at`, and the false-positive rate on (a) unblocked patrols, (b) patrols with a legitimate 2-sample pause, (c) stationary NPCs, (d) wandering NPCs. The model used is fitted on a separate set of synthetic patrol/wander/stationary tracks (train areas), never on the tracks it is scored on. The test asserts the detector flags at least 90% of blocked patrols within `window + 2` samples of the block and flags under 5% of the unblocked, paused and stationary ones; if the thresholds cannot meet those bounds, report the best achievable numbers and do NOT loosen the bounds in the test silently: say so in the Status row. On real tracks (when a dataset is present) the tool also prints how many tracks the detector flags, without claiming any are real blockages.

### Location model

- `location_data.py`: load thumbnails (80x72 greyscale uint8) into `(N,72,80)`, `area` labels, and the parsed cell as integers: Red `(x//4, y//4)`, Mario `(progress//128,)`; `weight` = `count` capped at 20.
- `location_baseline.py`: nearest-thumbnail (mean squared difference on the 80x72 images, one vectorised matrix operation per chunk of test thumbnails) giving area and cell of the nearest train thumbnail. This is the baseline to beat.
- `location_net.py`: a small CNN (three 3x3 conv blocks of 16, 32, 32 channels with ReLU and 2x2 pooling, global average pool) with two heads: the area class, and the cell as two small regression outputs (x and y cell, one output for Mario), trained on the train blocks; under 40 000 parameters; seeded; CPU; a 300 second wall-clock cap; no pretrained weights, no augmentation that changes position (a brightness jitter of +-10% is allowed). Inference milliseconds per frame is measured as in `time.perf_counter` median over 200 runs after 10 warm-up runs and reported with the CPU count.
- Metrics (`report.py`): area accuracy (specific, plus per-area accuracy with support), mean absolute cell error in cells and the share within one cell, each beside the baseline and beside a trivial predictor (the area's median cell).

### tools/motion_train.py

`uv run --frozen python tools/motion_train.py --game pokemon-red [--root runs/vision/pokemon-red] [--part movement|location|both] [--seed 0] [--max-seconds 300] [--synthetic]`. `--synthetic` runs the whole movement pipeline and the blocked-corridor report on generated tracks with no dataset, so the pipeline can be exercised anywhere. It prints the split rule first, then the tables, then writes `runs/vision_models/<game>/motion_report.json`; it refuses any output directory that is not inside a `runs` directory under the current working directory. A missing dataset directory prints a clear message and exits non-zero (except with `--synthetic`). Importing the file must not import torch.

### Legal and gitignore

Confirm `.gitignore` already has `runs/vision/`, `runs/vision_models/`, `*.pt`, `*.pth`, `*.npz` (directive 1 adds them); add any that are missing. The trained weights and reports are ROM-derived and stay local.

## What NOT to do

- Do not change `src/pokeagent/vision/`, `src/pokeagent/vision_model/`, `src/pokeagent/emulator.py`, `cli.py`, `explorer/`, the agent or any Pokemon behaviour. Do not wire any model into the agent loop or the explorer: this directive only trains and reports. `git diff --stat main -- src/pokeagent` must list only added files under `src/pokeagent/vision_motion/`.
- Do not split by random frame or random track anywhere, including in tests. Do not tune on the held-out set; it is scored once per run.
- Do not add torch (or anything) to `[project] dependencies`; do not import torch at module level anywhere.
- Do not run `uv lock`, `uv sync`, `pip` or any install or download. No pretrained models.
- Do not read `runs/`, `roms/` or `baselines/` in tests; no test needs a ROM or a dataset. Tests use `synthetic.py` and arrays built in the test.
- Do not commit any dataset, thumbnail, weights or report. No window. No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Do not state where any game copy came from.

## Verification (exact commands; Claude confirmed `uv run python --version` prints `Python 3.12.12` in this repo; do not run a bare version command, it is not in the sandbox list)

```
uv run --frozen pytest -q tests/test_motion_tracks.py tests/test_motion_movement.py tests/test_motion_nextpos.py tests/test_motion_blocked.py tests/test_motion_split.py tests/test_motion_location.py tests/test_motion_imports.py
```
Expected: all pass; torch tests are reported as skipped when torch is absent, which is acceptable here.

```
uv run --frozen python tools/motion_train.py --game pokemon-red --part movement --synthetic
```
Expected: prints the split rule, the movement tables and the `blocked_corridor` block, exits 0, writes only under `runs/`.

```
git diff --stat main -- src/pokeagent pyproject.toml
```
Expected: only added files under `src/pokeagent/vision_motion/` and, at most, the one added group in `pyproject.toml`.

```
uv run --frozen pytest -q
```
Expected: no new failures against main's tail; ROM-gated tests skip in this worktree.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command, for the reason given in the work.
- Branch only (`directive/pokeagent-movement-and-location-models-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and line counts in the Report.

## Completion criteria

- [ ] `tracks` groups rows by `(run, area, ident)` in frame order, never mixes areas, and the collapse/dwell helpers return the documented values on a hand-made track. <!-- test: tests/test_motion_tracks.py -->
- [ ] `label_track` follows the RAM rule (255 stationary, 254 walking, other or short -> None) and splits walking into patrolling vs wandering by collinearity and reversals; the features use only the first 24 rows; the decision-rule classifier beats the majority baseline on a synthetic mix and reports per-class accuracy with support for both three-way and stationary-vs-walking. <!-- test: tests/test_motion_movement.py -->
- [ ] The count-table next-position model beats `stay` and `continue` on non-stay steps for synthetic patrols, excludes diagonal and multi-tile jumps and counts them, and reports both overall and non-stay accuracy; the adoption rule function returns not adopted when the margin or support is short. <!-- test: tests/test_motion_nextpos.py -->
- [ ] The blocked-corridor fixture meets its bounds: at least 90% of 100 synthetic blocked patrols flagged within `window + 2` samples of the block, under 5% false positives on each of unblocked, 2-sample-pause, stationary and wandering sets, with the model fitted on separate synthetic tracks. <!-- test: tests/test_motion_blocked.py -->
- [ ] `split_tracks_by_area` and `split_thumbs_by_cell` are deterministic for a seed, hold out whole areas or whole `(area, cell)` blocks, raise `ValueError` for fewer than 3 areas, and remove any test thumbnail id that also occurs in a train block. <!-- test: tests/test_motion_split.py -->
- [ ] The nearest-thumbnail baseline recovers area and cell on synthetic thumbnails with distinct patterns, is vectorised, and the report gives area accuracy, mean cell error and within-one-cell share beside the trivial median-cell predictor; with torch the CNN trains on a synthetic set to above 0.9 held-out cell-block area accuracy in under 20 seconds and has under 40 000 parameters; without torch those tests skip. <!-- test: tests/test_motion_location.py -->
- [ ] A subprocess with torch import blocked can import `pokeagent`, every module in `pokeagent.vision_motion` and `tools/motion_train.py`, and `pyproject.toml` lists torch only in the `vision` group. <!-- test: tests/test_motion_imports.py -->
- [ ] `tools/motion_train.py --part movement --synthetic` runs and exits 0, and every new file is under its stated line limit.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails (which tests skipped for lack of torch), line counts of each new file, the thresholds chosen, and the printed `blocked_corridor` block from the synthetic run. Then the checks Claude runs afterwards with the ROM and torch (Claude's lane; Devin cannot do them):

1. `uv lock` and `uv sync --group vision`, then rerun `tests/test_motion_location.py` and the neural next-position test without skips.
2. Record real Pokemon Red play with directive 1 across several maps, then run `tools/motion_train.py` for movement and location; read the stationary-vs-walking accuracy first, the three-way accuracy second, next-position non-stay accuracy for stay, continue, count-table and (if run) neural, and the adoption line.
3. Verify the 0xC206 movement byte meaning (0xFF stay, 0xFE walk) on a known map with a known stationary NPC and a known wanderer; if the byte is wrong the movement labels are wrong and the numbers mean nothing.
4. Check the real-track blocked flags by eye against the replay, and the location split really holds out whole cells (print the blocks).
5. Confirm `git status` shows no weights, report or thumbnail outside gitignored paths.

## Forbidden Actions

- ROMs, extracted game art, thumbnails, position logs, datasets, trained weights and anything derived from them are ROM-derived: they stay local and gitignored. Never commit them, never add them to a fixture, never publish them.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not edit `src/pokeagent/vision/`, `src/pokeagent/vision_model/`, `src/pokeagent/emulator.py`, `src/pokeagent/cli.py`, `src/pokeagent/explorer/`, `roms/`, `baselines/`, or any Mario or Pokemon tool under `tools/`.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a window or send input in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- Directive 1 merged to main before dispatch (or the run branched from a base that contains it).
- The ROM and torch checks in the Report section, run by Claude after the verify lane passes (including `uv lock` and `uv sync --group vision`). Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(uv run --frozen python tools/motion_train.py)
- Exec(git diff)
- Exec(git grep)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-movement-and-location-models-directive |
| Base branch | - |
| Base commit | 8436b01f729e79bf14af444f7d6fd38363213713 |

**Status log**
- 2026-11-08 13:21 · robert-claude-laptop · none → Queued — Drafted by Claude for Robert: movement and location models (directive 3 of 3); needs directive 1 merged
- 2026-11-14 00:41 · robert-claude-laptop · Queued → Approved
- 2026-11-14 01:24 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-movement-and-location-models-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7CBM9BRG9GQXDA48J2JMWNF
- 2026-11-14 01:33 · dispatcher · launched pid=23972; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-movement-and-location-models-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (4 declared need(s), repo-scoped only))
<!-- queue:end -->
