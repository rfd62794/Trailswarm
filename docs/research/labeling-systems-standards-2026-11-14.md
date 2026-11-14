# Labeling systems and labeling QoL: standard, common, similar (2026-11-14)

## 1. Scope and the job
Subsystem: human labels for the cheap vision model (`src/pokeagent/vision_model/`, dataset `runs/vision/pokemon-red`). User: Robert,
solo with a day job, ~15 minute sessions. "Better" = fewer minutes per label that actually changes a result. Constraints: native Dear
PyGui only, ROM-derived crops local and gitignored, tests open no window. Queued: `Vision_Semantic_Labels` (labels from ROM tables;
water, doors, signs, trees are not derivable) and `Vision_Error_Triage` (buckets + most-confident-wrong).

## 2. What we do today
- Labels come only from RAM/OAM/ROM at record time (`tools/vision_record.py`, `src/pokeagent/vision/labels.py`); no human label path.
- Rows are already unique per image: `samples.jsonl` id = content sha, with a `count` field (`vision/dataset.py::iter_samples`).
- Honest held-out split by whole area plus leak removal by image id (`vision_model/split.py`).
- `unseen_in_train` counted, not dropped (`metrics.py`); triage and label-suspect list are research recs 1-3, queued/not built.
- Viewer (PR #268, `feat/vision-view`): class gallery, confusions, frame overlays; read-only, no editing.

## 3. Industry standard (web tools are pattern sources only)
- Prodigy (Explosion): one binary accept/reject card at a time, keyboard-first, active learning serves the most uncertain example
  next; stated aim is annotation fast enough for one person to do it (Prodigy docs, 2018-).
- Label Studio and CVAT: per-class hotkeys, undo, model predictions loaded as pre-annotations for correction; CVAT adds ground-truth
  jobs and honeypots to score annotators (Label Studio docs; CVAT docs, current).
- Labelbox and SageMaker Ground Truth: consensus across annotators and benchmark/gold items to measure quality (vendor docs, current).
- Snorkel: labeling functions give programmatic weak labels, humans cover only what the functions abstain on (Ratner et al., VLDB 2017).
- LabelMe/labelImg: single-user desktop-style annotation; shortcuts and next/previous image (Russell et al., IJCV 2008).

## 4. Common use cases
- Uncertainty sampling: label the examples the model is least sure of first; beats random on most tasks (Settles, UW-Madison TR 1648, 2009).
- Pre-label then correct: accepting or rejecting a model guess is much faster than labelling from scratch (Prodigy docs; CVAT auto-annotation).
- Label-noise audit: rank examples whose given label disagrees with confident out-of-sample predictions, review the top of the list
  only (confident learning / cleanlab, Northcutt, Jiang, Chuang, JAIR 70, 2021).
- Gold/held-out set creation: a small, carefully human-checked test set kept apart from training labels (Ground Truth, Labelbox benchmarks).
- Inter-annotator agreement (Cohen's kappa) only matters with more than one annotator; irrelevant for a solo user.

## 5. Similar use cases
- Tiled: tile properties (collision, custom class) set once per tile in the tileset, every placed instance inherits it (Tiled docs).
- Romhacking tile-type editors and BGB/mGBA tile viewers: edit a per-tile attribute table, not per-screen pixels (BGB manual; mGBA 0.8, 2020).
- VPT: contractors labelled actions for ~2k hours to train an inverse-dynamics model; spend was bought only for what the cheap model
  could not infer (Baker et al., NeurIPS 2022). MineRL used recorded human play as the label source (Guss et al., IJCAI 2019).
- NetHack Learning Environment: symbols are exact from the game, so no human labelling; the analogue of our ROM labels (Kuttler et al., NeurIPS 2020).
- PokemonRedExperiments: no vision labels at all; reads RAM (project docs, 2023-).

## 6. Comparison table
| Flow | Ours | Standard | Common | Similar | Verdict |
|---|---|---|---|---|---|
| L1 Programmatic labels first | ROM/RAM at record time | Snorkel LFs | weak supervision | NLE exact symbols | matches (better: ground truth, not heuristics) |
| L2 Dedupe, one label per image | id sha + `count` | n/a | dedupe near-duplicates | Tiled per-tile property | matches; not yet used for human labels |
| L3 Human label store | none | project DB + audit trail | append-only exports | tileset table | gap |
| L4 Queue by priority | none | active learning (Prodigy) | uncertainty sampling | VPT: only what model cannot infer | gap, highest value |
| L5 One-key accept / class keys / undo | none | Prodigy, CVAT, Label Studio hotkeys | same | n/a | gap |
| L6 Pre-label with model/ROM guess | none | predictions as pre-annotations | accept/reject | n/a | gap, cheap (guess = ROM class or net) |
| L7 Label-noise audit | planned (research rec 3) | cleanlab | review top-k | n/a | gap, planned |
| L8 Context around crop | thumbs + `find_boxes` in viewer | full image with box | same | VRAM/map viewers | partial, reusable |
| L9 Progress, timer, skip/unsure | none | CVAT/Prodigy progress | skip + flag | n/a | gap, cheap |
| L10 Gold set / agreement / consensus | held-out by area | gold + consensus | agreement stats | n/a | deliberate difference (solo; test set = held-out areas) |
| L11 Hosted/web, crowd | none | Label Studio, Labelbox, Ground Truth | MTurk | n/a | deliberate difference (native + local rule) |

## 7. Ranked recommendations
1. Human label store: append-only `labels_human.jsonl` keyed by image id; one label propagates to every row sharing that id; training
   reads it as an override with a `source` field (L2, L3; Tiled per-tile property).
2. Priority queue that only asks what data cannot decide: semantic `other`/undecidable classes first, then triage confident-wrong and
   label-suspect rows, deduped by id, highest `count` first (L4; Settles 2009, VPT).
3. Keyboard-first native tab: big crop, one number key per class, one key to accept the guess, U undo, S skip, ? unsure (L5, L6;
   Prodigy, CVAT). A `count`-ranked queue makes one keypress cover many rows.
4. Context frame around the crop, reusing `view_frames.find_boxes` on the stored thumbnail (L8).
5. Session progress, elapsed timer and seconds per label, so a 15 minute session shows what it bought (L9).
6. Later: label-suspect list from confident learning feeds the queue (L7); agreement stats only if a second annotator appears (L10).

Do not copy: Label Studio, CVAT, Labelbox, Ground Truth, Prodigy-as-a-service or any web/hosted tool (native-UI rule; they serve or
upload frames); crowdsourcing, contractors and consensus voting (solo user; ROM-derived images must not leave the machine); uploading
crops for pre-labelling by a cloud model; multi-annotator agreement machinery; free-text or bounding-box tools (crops are pre-cut).

## 8. Sources
Settles 2009 (burrsettles.com/pub/settles.activelearning.pdf); Northcutt et al. 2021 (arXiv 1911.00068, JAIR 70); Ratner et al. 2017
(arXiv 1711.10160); Baker et al. 2022 (arXiv 2206.11795); Guss et al. 2019 (arXiv 1907.13440); Kuttler et al. 2020 (arXiv 2006.13760);
Russell et al. 2008 (IJCV 77); Prodigy docs (prodi.gy/docs); Label Studio docs (labelstud.io/guide); CVAT docs (docs.cvat.ai);
Labelbox and SageMaker Ground Truth docs (current); Tiled docs (doc.mapeditor.org); BGB manual; mGBA 0.8.0 notes (2020).
Note: written without live fetches in this session; paper citations are from the published record, vendor-doc claims are general
behaviours. Re-open a link before quoting a number from it.
