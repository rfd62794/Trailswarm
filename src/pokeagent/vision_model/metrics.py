"""Accuracy reporting: per-class, coarse, confusions, and the honest unseen count."""
from __future__ import annotations

import numpy as np


def evaluate(pred_label, true_label, pred_coarse, true_coarse, class_names,
             weight=None, coarse_names=None, train_classes=None) -> dict:
    """Score predictions. ``train_classes`` is the set of class ids the model was
    trained on: a test row whose true class is absent counts in ``unseen_in_train``
    (and as an ordinary error) instead of being dropped silently."""
    pred_label, true_label = np.asarray(pred_label), np.asarray(true_label)
    pred_coarse, true_coarse = np.asarray(pred_coarse), np.asarray(true_coarse)
    n = len(true_label)
    w = np.ones(n) if weight is None else np.asarray(weight, np.float64)
    wsum = w.sum() or 1.0

    correct = pred_label == true_label
    per_class, accs = {}, []
    for cid, name in enumerate(class_names):
        m = true_label == cid
        sup = int(m.sum())
        per_class[name] = {
            "support": sup,
            "acc": float(correct[m].mean()) if sup else 0.0,
            "wacc": float((correct[m] * w[m]).sum() / w[m].sum()) if sup else 0.0}
        if sup:
            accs.append(per_class[name]["acc"])

    ccorrect = pred_coarse == true_coarse
    coarse_per_class = {}
    for c in np.unique(true_coarse):
        m = true_coarse == c
        name = (coarse_names[int(c)] if coarse_names is not None
                and 0 <= int(c) < len(coarse_names) else str(int(c)))
        coarse_per_class[name] = {"support": int(m.sum()),
                                  "acc": float(ccorrect[m].mean())}

    def cname(i):
        return class_names[i] if 0 <= i < len(class_names) else "?"

    conf: dict[tuple, int] = {}
    for t, p in zip(true_label.tolist(), pred_label.tolist()):
        if t != p:
            conf[(t, p)] = conf.get((t, p), 0) + 1
    top = sorted(conf.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    unseen = (int(sum(1 for t in true_label.tolist() if t not in train_classes))
              if train_classes is not None else 0)
    return {
        "overall": float(correct.mean()) if n else 0.0,
        "overall_weighted": float((correct * w).sum() / wsum),
        "macro": float(np.mean(accs)) if accs else 0.0,
        "coarse": float(ccorrect.mean()) if n else 0.0,
        "coarse_weighted": float((ccorrect * w).sum() / wsum),
        "per_class": per_class,
        "coarse_per_class": coarse_per_class,
        "top_confusions": [[cname(t), cname(p), c] for (t, p), c in top],
        "unseen_in_train": unseen}
