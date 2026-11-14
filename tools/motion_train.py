"""Train and score the movement and location models on a directive-1 dataset. Usage:
    uv run --frozen python tools/motion_train.py --game pokemon-red [--root R]
        [--part movement|location|both] [--seed 0] [--max-seconds 300] [--synthetic]
Prints the split rule first, then tables, then runs/vision_models/<game>/motion_report.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.vision_motion import (blocked, features, location_baseline, location_data,
                                   movement, nextpos, report, split, synthetic, tracks)

SPLIT_RULE = ("split: movement/next-position by whole held-out AREAS; location by whole "
              "held-out (area, cell) blocks - 'which map' for a map never seen in "
              "training is not defined and is not claimed")


def out_in_runs(out: Path, cwd: Path) -> bool:
    try:
        rel = out.resolve().relative_to(cwd.resolve())
    except ValueError:
        return False
    return rel.parts[:1] == ("runs",) or "runs" in rel.parts[:-1]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Train movement and location models.")
    ap.add_argument("--game", required=True)
    ap.add_argument("--root")
    ap.add_argument("--part", choices=("movement", "location", "both"), default="both")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-seconds", type=float, default=300.0)
    ap.add_argument("--synthetic", action="store_true")
    return ap.parse_args(argv)


def _movement(a) -> dict:
    if a.synthetic:
        all_t = synthetic.dataset(a.seed)
    else:
        from pokeagent.vision.dataset import iter_positions
        all_t = tracks.tracks_from_rows(iter_positions(a.root))
    train_t, test_t = split.split_tracks_by_area(all_t, seed=a.seed)
    tr = [(features.features(t), movement.label_track(t)) for t in train_t.values()]
    te = [(features.features(t), movement.label_track(t)) for t in test_t.values()]
    tr, te = [p for p in tr if p[1]], [p for p in te if p[1]]
    clf = movement.RuleTree().fit([x for x, _ in tr], [y for _, y in tr])
    maj = movement.Majority().fit([x for x, _ in tr], [y for _, y in tr])
    pred, pred_m = clf.predict([x for x, _ in te]), maj.predict([x for x, _ in te])
    truth = [y for _, y in te]
    out = {"excluded_tracks": {"train": len(train_t) - len(tr),
                               "test": len(test_t) - len(te)},
           "thresholds": movement.thresholds(clf),
           "stationary_vs_walking": report.per_class(
               [movement.walking_label(y) for y in truth],
               [movement.walking_label(p) for p in pred], ("stationary", "walking")),
           "three_way": {"rule": report.per_class(truth, pred, movement.LABELS),
                         "majority": report.per_class(truth, pred_m, movement.LABELS)}}
    steps_tr = [s for t in train_t.values() for s in nextpos.iter_steps(t)]
    steps_te = [s for t in test_t.values() for s in nextpos.iter_steps(t)]
    te_s = [(c, t) for c, t in steps_te if t is not None]
    table = nextpos.CountTable().fit(steps_tr)
    scores = {"stay": nextpos.evaluate(te_s, nextpos.stay_predict),
              "continue": nextpos.evaluate(te_s, nextpos.continue_predict),
              "count_table": nextpos.evaluate(te_s, table.predict)}
    out["nextpos"] = {"excluded": sum(t is None for _, t in steps_te), "scores": scores}
    out["neural"] = _neural(steps_tr, te_s, scores, a)
    out["blocked_corridor"] = blocked.blocked_report(a.seed)
    out["real_flagged"] = (None if a.synthetic else sum(
        blocked.flag_blocked(t, table) is not None for t in all_t.values()))
    return out


def _neural(steps_tr, te, scores, a) -> dict:
    try:
        __import__("torch")
    except ImportError:
        return {"status": "neural skipped: torch not installed"}
    from pokeagent.vision_motion import nextpos_net
    net = nextpos_net.train_net(steps_tr, seed=a.seed, max_seconds=a.max_seconds)
    s = nextpos.evaluate(te, lambda c: nextpos_net.predict(net, c))
    scores["neural"] = s
    ok = nextpos.adopt_neural(s["nonstay"], scores["count_table"]["nonstay"], s["n_nonstay"])
    return {"status": "neural adopted" if ok else "neural not adopted", "scores": s}


def _location(a) -> dict:
    d = location_data.load_thumbs(a.root)
    train, test = split.split_thumbs_by_cell(d["rows"], seed=a.seed)
    tri, tei = ([d["rows"].index(r) for r in s] for s in (train, test))
    idx = location_baseline.nearest(d["images"][tri], d["images"][tei])
    areas = [d["areas"][i] for i in tri]
    return {"n_test": len(tei),
            "baseline": {"area_acc": report.accuracy(
                [d["areas"][i] for i in tei], [areas[j] for j in idx]),
                "cell": location_baseline.cell_error(d["cells"][tei], d["cells"][tri][idx])},
            "trivial_cell": location_baseline.cell_error(
                d["cells"][tei], location_baseline.median_cell_predict(
                    areas, d["cells"][tri], [d["areas"][i] for i in tei]))}


def main(argv=None) -> int:
    a = parse_args(argv)
    out_dir = Path("runs") / "vision_models" / a.game
    if not out_in_runs(out_dir, Path.cwd()):
        print(f"error: {out_dir} is not inside a runs directory", file=sys.stderr)
        return 2
    a.root = Path(a.root) if a.root else Path("runs") / "vision" / a.game
    if not a.synthetic and not a.root.is_dir():
        print(f"error: dataset {a.root} not found (use --synthetic)", file=sys.stderr)
        return 2
    rep = {"game": a.game, "seed": a.seed, "split_rule": SPLIT_RULE}
    print(SPLIT_RULE)
    if a.part in ("movement", "both") or a.synthetic:
        r = rep["movement"] = _movement(a)
        print(report.table(r["stationary_vs_walking"], "stationary vs walking (RAM truth)"))
        print(report.table(r["three_way"]["rule"], "three-way (trajectory labels)"))
        print(report.table(r["three_way"]["majority"], "three-way majority baseline"))
        print(report.model_scores(r["nextpos"]["scores"]))
        print(r["neural"]["status"])
        print(json.dumps({"blocked_corridor": r["blocked_corridor"]}, indent=2))
        if r["real_flagged"] is not None:
            print(f"real tracks flagged (not claimed blockages): {r['real_flagged']}")
    if a.part in ("location", "both") and not a.synthetic:
        rep["location"] = _location(a)
        print(json.dumps(rep["location"], indent=2))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "motion_report.json").write_text(json.dumps(rep, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
