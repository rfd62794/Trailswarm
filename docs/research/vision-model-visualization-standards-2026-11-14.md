# Vision-model visualization: standard, common, similar (2026-11-14)

## 1. Scope and the job
Subsystem: the cheap vision model (`src/pokeagent/vision_model/`, `tools/vision_train.py`, `tools/vision_record.py`) and the
location/motion models (`src/pokeagent/vision_motion/`). User: Robert, solo, watching the agent. "Better" = at a glance he sees
what the model gets right/wrong and what to fix next (labels vs model vs data). Constraints: Dear PyGui native window only (no
web/phone views, no hosted dashboards), ROM-derived images local and never published, CPU, 22.8k-param CNN on 16x16 crops.

## 2. What we do today
- Net: `TinyNet` with a specific-class head plus a 6-way coarse head (`vision_model/net.py`); nearest-template baseline (`template.py`).
- Honest split: held-out by whole areas, never by frame (`split.py`); unseen-in-train rows are counted, not dropped (`metrics.py`).
- Numbers as text/JSON: overall, macro, coarse, per-class support/acc, top-10 confusions (name, name, count), `unseen_in_train`
  (`metrics.py`, `report.json` via `tools/vision_train.py`); measured ms per crop and per frame (`bench.py`).
- Location/motion models print a fixed-width per-class text table (`vision_motion/report.py`), with a nearest-image baseline.
- Local-only weights and class table (`export.py`); dataset recorded headless from RAM labels (`tools/vision_record.py`).
- In progress (branch `feat/vision-view`, `tools/vision_view.py`, Dear PyGui; not yet merged): tabs for model's-eye frame overlay
  (green right / red wrong / grey unseen, plus coarse-colour overlay), class gallery true-vs-predicted, top-10 confusions,
  conv1 filter images, architecture + headline numbers.
- Real numbers: held-out maps 101/64/66; template 9.6%, net 2.2%, coarse ~99.9%; 573/1287 test rows are unseen classes
  because labels are tile-id@tileset.

## 3. Industry standard
- Confusion matrix with row/column normalisation: scikit-learn `ConfusionMatrixDisplay(normalize='true'|'pred'|'all')`; TensorBoard's
  image-summary tutorial logs one per epoch as the first classifier diagnostic (scikit-learn 1.x docs; TensorFlow docs).
- Per-prediction browsing: W&B Tables put input image, ground truth, prediction and confidence side by side, filterable/sortable,
  and compare two models on the same key (W&B docs, current). FiftyOne stores per-sample TP/FP/FN counts so you sort by most
  errors and click a confusion-matrix cell to select those samples (Voxel51 docs, current).
- Feature/saliency views: Grad-CAM heat maps of the last conv layer (Selvaraju et al., ICCV 2017); feature visualization and
  "semantic dictionaries" pairing each unit with its picture (Olah et al., Distill 2017 and 2018); activation atlases (Distill 2019).
- Reliability/calibration diagrams: scikit-learn `CalibrationDisplay` (listed in its Visualizations guide).

## 4. Common use cases
- Error analysis: worst confusions and most-confident-wrong, via sorted sample tables (W&B error-analysis report; FiftyOne `eval_fp` sort).
- Label-error finding: confident learning estimates the joint distribution of given vs true labels and ranks suspect examples;
  open-sourced as cleanlab (Northcutt, Jiang, Chuang, JAIR 70, 2021). This is the "labels vs model" question directly.
- Class-balance/coverage: per-class support next to per-class accuracy (scikit-learn classification-report convention; W&B Tables grouping).
- Train vs held-out slices: compare the same table under two filters/keys (W&B "same key" comparison; FiftyOne views).

## 5. Similar use cases
- Atari agents: perturbation saliency videos show whether an agent acts for the right reason, and a user study found they
  helped non-experts reason about the agent (Greydanus et al., ICML 2018).
- DQN: t-SNE of last-hidden-layer states, human and agent play overlaid, to show similar state sequences (Mnih et al., Nature 2015, Extended Data Fig. 1).
- PokemonRedExperiments: a live map of where agents have been, used to spot weak exploration and reward exploitation
  (Whidden et al., project docs and arXiv 2502.19920, 2025).
- Native tile/VRAM viewers: BGB's VRAM viewer (BG map, tiles, OAM, palettes) and mGBA's map/sprite viewers with tile export
  (BGB manual; mGBA 0.8.0 release notes, 2020). Plot-in-native-UI precedent: ImPlot supports heatmaps and images, with a vertex cap on dense heatmaps (epezent/implot README).
- Detection overlays: boxes with ground-truth and prediction toggled/stacked on the image (W&B media panel docs).

## 6. Comparison table
| Capability / flow | Ours | Standard | Common | Similar | Verdict |
|---|---|---|---|---|---|
| R1 Headline metrics | overall/macro/coarse + unseen count | per-class report | same | n/a | matches (unseen count is better, see below) |
| R2 Confusion view | top-10 list (text) | full normalised matrix | click cell to see samples | n/a | partial; viewer adds list, no matrix |
| R3 Per-frame right/wrong overlay | in progress (viewer) | prediction tables with images | sort by FP | detection overlays, Atari saliency | in progress |
| R4 Most-confident-wrong browser | none | confidence column, sortable | core error-analysis flow | n/a | gap |
| R5 Label-error finding | none; 573/1287 rows are unseen ids | n/a | confident learning / cleanlab | n/a | gap, highest value for "labels vs model" |
| R6 Class coverage vs accuracy | support + acc in JSON, no view | support next to acc | class-balance view | n/a | partial |
| R7 Train vs held-out slice compare | held-out only; baseline vs net in report | two keys side by side | slice comparison | n/a | gap (cheap) |
| R8 Saliency / what the net uses | in progress (conv1 filters only) | Grad-CAM, feature viz | optional | Atari saliency | partial; 16x16 crop makes it cheap |
| R9 Embedding view | none | projector, t-SNE | uncommon for classifiers | DQN t-SNE | gap, low priority |
| R10 Calibration | none | reliability diagram | occasional | n/a | gap, low priority |
| R11 Architecture view | in progress (text in viewer) | Netron | same | n/a | matches for 22.8k params |
| R12 Hosted/web dashboard | none (native only) | TensorBoard, W&B | same | web VRAM viewers exist | deliberate difference (native UI rule) |

## 7. Ranked recommendations (value over cost, cheapest first)
1. Add a "label vs model vs data" triage line to the viewer and `report.json`: split errors into unseen-class (data/labels),
   coarse-correct-fine-wrong (label granularity), and coarse-wrong (model). Pure counts from existing arrays. (R1, R5, R6)
2. Most-confident-wrong gallery: sort test crops by softmax confidence among errors; show crop, true, predicted, map. Needs the
   viewer to keep softmax maxima, nothing else. (R4)
3. Label-suspect list: apply confident learning (cleanlab's method, or a 30-line per-class threshold version in a small module)
   on held-out softmax outputs; list crops whose confident label disagrees with the tile-id@tileset label. Feeds the semantic-labels
   directive. (R5)
4. Normalised confusion heatmap tab (rows = true, `normalize='true'`) grouped by coarse class, using a DPG heatmap/drawlist, with
   click-to-list crops. Replaces the top-10 text. (R2)
5. Train-vs-held-out and template-vs-net side-by-side per class, plus a support-vs-accuracy bar (coverage). (R6, R7)
6. Occlusion saliency for a selected crop: slide a small grey patch over the 16x16 crop, plot the confidence drop (Greydanus-style
   perturbation; 256 forward passes, sub-second on CPU). Simpler and more honest than Grad-CAM on a 3-conv net. (R8)
7. Reliability diagram (ten bins, one drawlist) once recommendation 2 stores confidences. (R10)

Do not copy: TensorBoard, W&B, FiftyOne, Microscope or any hosted/web dashboard (native-UI rule; they upload or serve frames);
anything that uploads frames or crops; publishing sprite/tile galleries, saliency images or overlays (ROM-derived, local only);
t-SNE/UMAP projector and Lucid/Captum feature-viz optimisation at this scale (R9: 22.8k params, little to learn); Netron or any
architecture tool beyond the text summary; heavyweight dependencies (cleanlab itself is optional; the method is small).
Patterns from the web tools are ported to the Dear PyGui window, never adopted as products.

## 8. Sources
- Selvaraju et al., Grad-CAM, ICCV 2017: https://arxiv.org/abs/1610.02391
- Olah et al., The Building Blocks of Interpretability, Distill 2018: https://distill.pub/2018/building-blocks/
- Carter et al., Activation Atlases, Distill 2019: https://distill.pub/2019/activation-atlas
- Greydanus et al., Visualizing and Understanding Atari Agents, ICML 2018: https://proceedings.mlr.press/v80/greydanus18a.html
- Mnih et al., Nature 2015: https://www.doi.org/10.1038/NATURE14236
- Northcutt, Jiang, Chuang, Confident Learning, JAIR 70, 2021: https://jair.org/index.php/jair/article/view/12125
- scikit-learn ConfusionMatrixDisplay: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.ConfusionMatrixDisplay
- TensorBoard image summaries (confusion matrix): https://www.tensorflow.org/tensorboard/image_summaries
- W&B Tables, evaluate models: https://docs.wandb.ai/models/tables/evaluate-models
- FiftyOne evaluating models: https://docs.voxel51.com/user_guide/evaluation/index.html
- BGB manual: https://bgb.bircd.org/manual.html ; mGBA 0.8.0: https://mgba.io/2020/01/21/mgba-0.8.0
- ImPlot: https://github.com/epezent/implot
- PokemonRedExperiments metrics and visualization: https://drubinstein.github.io/pokerl/docs/chapter-3/metrics ; https://arxiv.org/abs/2502.19920
- Not independently fetched (search summaries only): Distill Feature Visualization 2017 (cited via Building Blocks), W&B media panel, FiftyOne mistakenness.
