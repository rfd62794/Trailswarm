"""Sort every held-out prediction into one triage bucket; rank confident errors.

Buckets, first match wins: correct, unseen_in_train (a data/label problem),
coarse_wrong (a model problem), coarse_right_fine_wrong (label granularity or
fine discrimination). Pure numpy, so it runs without the optional vision deps.
"""
from __future__ import annotations

import numpy as np

BUCKETS = ("correct", "unseen_in_train", "coarse_wrong",
           "coarse_right_fine_wrong")


def triage(true_label, pred_label, true_coarse, pred_coarse, confidence,
           train_classes, ids, class_names=None, top_n=20) -> dict:
    """One bucket per held-out row, plus the wrong rows sorted by confidence
    descending (ties by id ascending). ``train_classes`` is the set of class
    ids seen in training; a wrong row whose true id is absent lands in
    ``unseen_in_train`` regardless of the coarse outcome."""
    true_label = np.asarray(true_label)
    pred_label = np.asarray(pred_label)
    true_coarse = np.asarray(true_coarse)
    pred_coarse = np.asarray(pred_coarse)
    confidence = np.asarray(confidence, np.float64)
    ids = np.asarray(ids, str)
    n = len(true_label)
    if any(len(a) != n
           for a in (pred_label, true_coarse, pred_coarse, confidence, ids)):
        raise ValueError("inputs must be equal-length 1-D arrays")
    if top_n < 0:
        raise ValueError("top_n must be >= 0")

    correct = pred_label == true_label
    unseen = np.fromiter((int(t) not in train_classes
                          for t in true_label), bool, n)
    cwrong = pred_coarse != true_coarse
    bucket = np.where(correct, 0, np.where(unseen, 1, np.where(cwrong, 2, 3)))
    counts = {name: int((bucket == i).sum()) for i, name in enumerate(BUCKETS)}

    def cname(i):
        return (str(class_names[i]) if class_names is not None
                and 0 <= i < len(class_names) else "?")

    wrong = np.flatnonzero(~correct)
    order = wrong[np.lexsort((ids[wrong], -confidence[wrong]))]
    entries = [{"id": str(ids[i]), "true": cname(int(true_label[i])),
                "pred": cname(int(pred_label[i])),
                "confidence": round(float(confidence[i]), 4),
                "bucket": BUCKETS[int(bucket[i])]}
               for i in order[:top_n]]
    return {"n": n, "counts": counts, "wrong": n - counts["correct"],
            "confident_wrong": entries}


def format_text(result, top=5) -> str:
    """One counts line - wrong buckets as a share of wrong rows - plus the
    first ``top`` confident-wrong entries as ``id true -> pred conf bucket``."""
    c = result["counts"]
    w = result["wrong"]
    pct = lambda b: c[b] / w * 100 if w else 0.0
    lines = [f"triage n={result['n']} correct {c['correct']} | "
             f"unseen_in_train {c['unseen_in_train']} "
             f"({pct('unseen_in_train'):.1f}%) | "
             f"coarse_wrong {c['coarse_wrong']} ({pct('coarse_wrong'):.1f}%) | "
             f"coarse_right_fine_wrong {c['coarse_right_fine_wrong']} "
             f"({pct('coarse_right_fine_wrong'):.1f}%) of wrong"]
    for e in result["confident_wrong"][:top]:
        lines.append(f"  {e['id'][:8]} {e['true']} -> {e['pred']} "
                     f"{e['confidence']:.4f} {e['bucket']}")
    return "\n".join(lines)
