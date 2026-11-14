# PokeAgent: vision error triage - sort every held-out error into data, label-granularity or model, and rank the most-confident wrong predictions

## Why this exists

Robert, 2026-11-14, approved (research note vision-model-visualization-standards-2026-11-14, PokeAgent PR 267, recommendations 1 and 2). The cheap vision model scores 2.2% overall against a 9.6% template baseline on held-out maps 101/64/66, with coarse sprite-vs-terrain at about 99.9%, and 573 of 1287 test rows are classes never seen in training (labels are tile-id@tileset). Today `report.json` gives one overall number and a top-10 confusion list, so Robert cannot tell whether to fix the data, the labels or the model. This directive adds a pure triage that puts every held-out row in exactly one bucket and lists the wrong predictions the net was most sure about (those are the first place to look for label errors). A viewer is being built separately (branch `feat/vision-view`); this directive only produces the numbers it can later show.

Buckets, one per row, with this precedence (first match wins):
1. `correct`: predicted class equals true class.
2. `unseen_in_train`: wrong, and the true class id is not in the training class set (a data/label problem, no model could get it).
3. `coarse_wrong`: wrong, true class was seen in training, and the coarse class is also wrong (a model problem).
4. `coarse_right_fine_wrong`: wrong, class seen in training, coarse right (a label-granularity or fine-discrimination problem).

Facts the agent needs (pasted, because the worktree cannot be searched beyond the files named here; claude confirmed `uv run python --version` prints `Python 3.12.12`):

`src/pokeagent/vision_model/net.py` today (torch imported inside function bodies only; torch is NOT installed in this worktree, so torch tests skip):
```
def TinyNet(n_classes: int):         # forward(x) -> (class_logits, coarse_logits); x is (B,3,16,16) float 0..1
def predict(model, images, batch=512) -> tuple[np.ndarray, np.ndarray]:
    """(class id, coarse id) per crop; deterministic, no grad."""
    import torch
    model.eval()
    ... x = torch.from_numpy(np.ascontiguousarray(images[s:s + batch])).float().div_(255.0).permute(0, 3, 1, 2)
    logits, coarse = model(x)
    lab[s:s + batch] = logits.argmax(1).numpy(); co[s:s + batch] = coarse.argmax(1).numpy()
```
`src/pokeagent/vision_model/metrics.py`: `evaluate(pred_label, true_label, pred_coarse, true_coarse, class_names, weight=None, coarse_names=None, train_classes=None) -> dict` returns keys `overall, overall_weighted, macro, coarse, coarse_weighted, per_class, coarse_per_class, top_confusions, unseen_in_train`. `unseen_in_train` counts rows whose true id is not in `train_classes`. Reuse the same definition; do not change `evaluate`.

`src/pokeagent/vision_model/data.py`: frozen dataclass `Dataset` with arrays `images, label, coarse, area, kind, bank, weight, w, h, ids` (`ids` is a content id string per row); `COARSE = ("enemy","npc","item","player","terrain","other")`.

`tools/vision_train.py` `main()`, the part you will extend (class ids: `table` maps training keys to dense ids; test rows whose key is not in `table` get fresh ids `>= len(table)` appended to `full`, and `names` is the id-indexed name list; unseen names end with " (unseen)"):
```
    y_true = data.encode(test_ds, full)
    ...
    res = net.train(ds, train_idx, table, epochs=a.epochs, seed=a.seed, threads=a.threads, max_seconds=a.max_seconds)
    n_lab, n_co = net.predict(res.model, test_ds.images)
    n_rep = metrics.evaluate(n_lab, y_true, n_co, test_ds.coarse, names, weight=test_ds.weight,
                             coarse_names=data.COARSE, train_classes=set(table.values()))
    _print_report("net", n_rep)
    ...
    report = {"game": a.game, "seed": a.seed, "params": ..., "areas": {...}, "rows": {...},
              "template": t_rep, "net": n_rep, "bench": {...}, "train": {...}}
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
```
`report.json` lives under `runs/vision_models/<game>/`, which is gitignored (`.gitignore` line `runs/`).

## Scope (in this order)

1. `src/pokeagent/vision_model/triage.py` <!-- new: src/pokeagent/vision_model/triage.py --> - the pure triage. Under 150 lines.
2. `src/pokeagent/vision_model/net.py` - add ONE new function `predict_with_confidence`; do not change `predict` or any existing signature.
3. `tools/vision_train.py` - minimal change: add a `"triage"` section to `report.json` and a short stdout block.
4. `tests/test_vision_triage.py` <!-- new: tests/test_vision_triage.py --> - synthetic arrays only.

## The work

### triage.py (pure numpy; no torch import anywhere, not even inside a function)

```
BUCKETS = ("correct", "unseen_in_train", "coarse_wrong", "coarse_right_fine_wrong")

def triage(true_label, pred_label, true_coarse, pred_coarse, confidence, train_classes, ids,
           class_names=None, top_n=20) -> dict
```
- Inputs are equal-length 1-D arrays (`ids` an array of strings; `train_classes` a set of ints; `class_names` an optional id-indexed list; a missing or out-of-range id prints as `"?"`). Raise `ValueError` on unequal lengths or `top_n < 0`. Empty input returns zero counts and an empty list.
- Returns `{"n": N, "counts": {bucket: int for each of BUCKETS}, "wrong": N - counts["correct"], "confident_wrong": [...]}`. The counts sum to N and each wrong row is in exactly one wrong bucket by the precedence above.
- `confident_wrong` is every wrong row sorted by `confidence` descending, ties broken by `id` ascending (use a stable `np.lexsort` or `sorted` with the key `(-confidence, id)`), cut to `top_n`. Each entry is a dict `{"id": str, "true": name, "pred": name, "confidence": float rounded to 4 places, "bucket": str}`. It includes rows of every wrong bucket (the `bucket` field says which). Convert numpy scalars to plain Python `int`/`float`/`str` so `json.dumps` works.
- `format_text(result, top=5) -> str`: a short block for stdout: one line of counts (`correct`, `unseen_in_train`, `coarse_wrong`, `coarse_right_fine_wrong`, with each wrong bucket as a percentage of wrong rows) and the first `top` confident-wrong entries as `id[:8] true -> pred conf bucket`. No ids or pixel data beyond the 8-character id prefix.

### net.py: one new function

```
def predict_with_confidence(model, images, batch=512) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(class id, coarse id, confidence) per crop; confidence is the max softmax of the class head."""
```
Same loop and preprocessing as `predict` (copy the five lines; do not refactor `predict`), `torch.no_grad()`, `torch.softmax(logits, 1).max(1).values.numpy()` as float32. `net.py` stays under 150 lines.

### tools/vision_train.py

After the net's `predict`, call `net.predict_with_confidence` instead of `net.predict` (one call gives labels, coarse and confidence; keep the variable names `n_lab`, `n_co`, add `n_conf`), then `triage.triage(y_true, n_lab, test_ds.coarse, n_co, n_conf, set(table.values()), test_ds.ids, class_names=names)`. Put the result in `report["triage"]` and print `triage.format_text(...)` after `_print_report("net", n_rep)`. Add `triage` to the existing `from pokeagent.vision_model import ...` line. Do not change any other behaviour, flag or output. The template baseline gets no triage (it has no confidence).

## What NOT to do

- Do not touch the viewer tool being built on branch `feat/vision-view`, any file on the `feat/vision-view` branch, `src/pokeagent/vision/`, the semantic-labels work (labels stay tile-id@tileset), `src/pokeagent/emulator.py`, `cli.py`, `roms/`, `baselines/`, or any other module under `src/pokeagent/vision_model/` (`metrics.py` included).
- Do not change `net.predict`'s signature or return, `metrics.evaluate`, or the existing `report.json` keys; only add `"triage"`.
- Do not import torch at module level anywhere, and not in `triage.py` at all. Do not add dependencies. Do not run `uv lock`, `uv sync`, `pip` or any install or download.
- Do not read `runs/`, `roms/` or `baselines/`; no test may need a ROM, a dataset or torch to pass (torch tests skip).
- Do not render, write or commit any image. No window. No scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- Do not state where any game copy came from.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`; do not run a bare version command)

```
uv run pytest -q -p no:cacheprovider tests/test_vision_triage.py
```
Expected: all pass; the one torch test is reported as skipped (torch is absent here), and that is acceptable.

```
uv run pytest -q -p no:cacheprovider tests/test_vision_model_data.py tests/test_vision_model_split.py tests/test_vision_model_template.py tests/test_vision_model_metrics.py tests/test_vision_model_net.py tests/test_vision_model_bench.py tests/test_vision_model_imports.py
```
Expected, as measured by Claude on origin/main 19ca1b2 before this change: `14 passed, 6 skipped, 1 warning`. After your change the numbers must be the same.

```
git diff --stat origin/main -- src tools
```
Expected: one added file `src/pokeagent/vision_model/triage.py`, a small edit to `src/pokeagent/vision_model/net.py` (one added function) and to `tools/vision_train.py`.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run pytest -q -p no:cacheprovider <files>` for every test command.
- Branch only (`directive/vision-error-triage-directive`); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat, test tails and line counts in the Report.

## Completion criteria

- [ ] `triage` puts every row in exactly one bucket with the stated precedence (unseen beats coarse_wrong beats coarse_right_fine_wrong); counts sum to N; `wrong` equals N minus `correct`. <!-- test: tests/test_vision_triage.py -->
- [ ] A synthetic case with one row of each bucket, plus one row that is both unseen and coarse-wrong, lands in the expected buckets. <!-- test: tests/test_vision_triage.py -->
- [ ] `confident_wrong` lists only wrong rows, sorted by confidence descending with ties broken by id ascending, is cut to `top_n`, is deterministic across repeated calls and across a shuffled input order, and `json.dumps(result)` succeeds. <!-- test: tests/test_vision_triage.py -->
- [ ] Unequal lengths and a negative `top_n` raise `ValueError`; empty input returns zero counts and an empty list; an out-of-range class id prints as `"?"`. <!-- test: tests/test_vision_triage.py -->
- [ ] `triage.py` imports without torch (subprocess with a `torch` stub that raises `ImportError`) and contains no torch import at all; it is under 150 lines. <!-- test: tests/test_vision_triage.py -->
- [ ] `format_text` output contains all four bucket names and at most `top` confident-wrong lines. <!-- test: tests/test_vision_triage.py -->
- [ ] With torch present (`pytest.importorskip("torch")` inside the test), `net.predict_with_confidence` agrees with `net.predict` on labels and coarse, returns confidences in `[1/n_classes, 1]`, and is deterministic; without torch it skips. <!-- test: tests/test_vision_triage.py -->
- [ ] `tools/vision_train.py` adds only the `triage` import, the `predict_with_confidence` call, the `report["triage"]` entry and one print; `net.predict`'s signature is unchanged (checked by `git diff`).
- [ ] The existing vision-model tests give the same `14 passed, 6 skipped` as before.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails (including which test skipped for lack of torch), line counts of `triage.py` and the changed files. Then the checks Claude runs afterwards with the dataset and torch (Claude's lane; Devin cannot do them):

1. With torch installed, rerun `tests/test_vision_triage.py` without skips.
2. Run `tools/vision_train.py` for Pokemon Red on real data and read the triage counts: expect `unseen_in_train` near 573 of 1287, and check that the four buckets sum to the test row count and that `unseen_in_train` equals `report["net"]["unseen_in_train"]`.
3. Read the top confident-wrong list and decide per entry whether the label, the data or the model is at fault, and report that split to Robert.
4. Confirm `git status` shows no weights, report or image outside gitignored paths.

## Forbidden Actions

- ROMs, extracted game art, datasets, trained weights and anything derived from them are ROM-derived: they stay local and gitignored. Never commit them, never add them to a fixture, never publish them.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not edit the viewer tool or anything from branch `feat/vision-view`, `src/pokeagent/vision/`, `src/pokeagent/emulator.py`, `src/pokeagent/cli.py`, `roms/`, `baselines/`, or any Mario or Pokemon tool under `tools/` other than `tools/vision_train.py`.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor; do not edit another directive's queue block.
- Do not open a window or send input in tests or while checking your work.
- Do not commit to or push main, merge, or deploy.

## Required from User

- None. The run needs no dataset and no torch; Claude does the real-data checks afterwards.

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
- 2026-11-14 12:39 · robert-claude-laptop · Queued → Approved
<!-- queue:end -->
