"""Train and score the cheap sprite model against the nearest-template baseline.

    uv run --frozen python tools/vision_train.py --game pokemon-red \
        [--root runs/vision/pokemon-red] [--epochs 30] [--seed 0] [--threads 1] \
        [--max-seconds 300] [--kinds sprite,tile] [--labels specific]

Held-out evaluation is by whole areas, never by frame. Writes
runs/vision_models/<game>/ (weights.pt, classes.json, report.json; local, gitignored).
With --labels semantic the dataset is viewed through its relabelled semantic class
(one class table across tiles and sprites) and output goes to <game>-semantic/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.vision_model import bench, data, metrics, semantic_view, split, template, triage


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Train the cheap vision model.")
    ap.add_argument("--game", required=True)
    ap.add_argument("--root")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--max-seconds", type=int, default=300)
    ap.add_argument("--kinds", default="sprite,tile")
    ap.add_argument("--labels", choices=("specific", "semantic"), default="specific")
    return ap.parse_args(argv)


def _print_report(name, rep):
    print(f"{name}: overall {rep['overall']:.3f} (weighted "
          f"{rep['overall_weighted']:.3f}) macro {rep['macro']:.3f} "
          f"coarse {rep['coarse']:.3f} | unseen_in_train {rep['unseen_in_train']}")
    for cname, row in rep["per_class"].items():
        if row["support"]:
            print(f"  {cname:<26} n={row['support']:<5} acc={row['acc']:.3f}")


def main(argv=None) -> int:
    a = parse_args(argv)
    root = Path(a.root) if a.root else Path("runs") / "vision" / a.game
    if not root.is_dir():
        print(f"error: dataset directory {root} is missing", file=sys.stderr)
        return 2
    ds = data.load_dataset(root, tuple(a.kinds.split(",")))
    if a.labels == "semantic":
        try:
            ds = semantic_view.as_semantic(ds)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    name_of = semantic_view.class_name if a.labels == "semantic" else data.class_name
    train_areas, test_areas = split.split_by_area(ds.area, seed=a.seed)
    print(f"train areas ({len(train_areas)}): {sorted(train_areas)}")
    print(f"test areas  ({len(test_areas)}): {sorted(test_areas)}")
    train_idx = split.area_indices(ds.area, train_areas)
    test_idx = split.area_indices(ds.area, test_areas)
    test_idx, removed = split.drop_leaking_test_rows(ds, train_idx, test_idx)
    split.assert_disjoint(train_idx, test_idx, ds)
    print(f"rows: {len(train_idx)} train / {len(test_idx)} test "
          f"({removed} test rows dropped: image id also in a train area)")
    train_ds, test_ds = ds.select(train_idx), ds.select(test_idx)
    table = data.class_table(train_ds)
    names = [name_of(k) for k in sorted(table, key=table.get)]
    full = dict(table)                      # unseen test classes get fresh ids
    for i in range(len(test_ds.label)):
        key = data.row_key(test_ds, i)
        if key not in full:
            full[key] = len(full)
            names.append(name_of(key) + " (unseen)")
    y_true = data.encode(test_ds, full)
    tmpl = template.fit_templates(ds, train_idx, table)
    t_lab, t_co = template.predict_templates(
        tmpl, test_ds.images, test_ds.kind, test_ds.bank)
    t_rep = metrics.evaluate(t_lab, y_true, t_co, test_ds.coarse, names,
                             weight=test_ds.weight, coarse_names=data.COARSE,
                             train_classes=set(table.values()))
    _print_report("template", t_rep)
    try:
        import torch  # noqa: F401
    except ImportError:
        print("torch is not installed; `uv sync --group vision` is needed")
        return 2
    from pokeagent.vision_model import export, net
    res = net.train(ds, train_idx, table, epochs=a.epochs, seed=a.seed,
                    threads=a.threads, max_seconds=a.max_seconds)
    n_lab, n_co, n_conf = net.predict_with_confidence(res.model, test_ds.images)
    n_rep = metrics.evaluate(n_lab, y_true, n_co, test_ds.coarse, names,
                             weight=test_ds.weight, coarse_names=data.COARSE,
                             train_classes=set(table.values()))
    _print_report("net", n_rep)
    if a.labels == "semantic":
        print("\n".join(metrics.side_by_side(t_rep, n_rep)))
    tri = triage.triage(y_true, n_lab, test_ds.coarse, n_co, n_conf,
                        set(table.values()), test_ds.ids, class_names=names)
    print(triage.format_text(tri))
    out = Path("runs") / "vision_models" / (a.game if a.labels == "specific"
                                            else f"{a.game}-semantic")
    export.save(res.model, table, out)
    report = {"game": a.game, "seed": a.seed, "params": net.param_count(res.model),
              "areas": {"train": sorted(train_areas), "test": sorted(test_areas)},
              "rows": {"train": len(train_idx), "test": len(test_idx),
                       "leak_removed": removed},
              "template": t_rep, "net": n_rep, "triage": tri,
              "bench": {"net": bench.measure(res.model, threads=a.threads),
                        "template": bench.measure_template(tmpl, threads=a.threads)},
              "train": {"epochs": res.epochs, "seconds": res.seconds,
                        "stopped_by_clock": res.stopped_by_clock, "loss": res.loss}}
    if a.labels == "semantic":
        report["labels"] = "semantic"
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n",
                                     encoding="utf-8")
    nb = report["bench"]["net"]
    print(f"params {report['params']} | unseen_in_train {n_rep['unseen_in_train']} | "
          f"ms/crop {nb['ms_per_crop']:.3f} ms/frame {nb['ms_per_frame']:.1f} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
