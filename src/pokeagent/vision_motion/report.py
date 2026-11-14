"""Accuracy helpers and the report dict / text table shared by both model parts. Pure."""
from __future__ import annotations


def accuracy(truth, pred) -> float:
    n = len(truth)
    return sum(t == p for t, p in zip(truth, pred)) / n if n else 0.0


def per_class(truth, pred, labels) -> dict:
    """``{label: {"n": support, "acc": accuracy on that label's rows}}`` plus ``"_all"``."""
    out = {}
    for lab in labels:
        idx = [i for i, t in enumerate(truth) if t == lab]
        out[lab] = {"n": len(idx),
                    "acc": (sum(pred[i] == lab for i in idx) / len(idx)) if idx else None}
    out["_all"] = {"n": len(truth), "acc": accuracy(truth, pred)}
    return out


def table(rep: dict, title: str = "", order=None) -> str:
    """A fixed-width text table for a ``per_class`` report dict."""
    lines = [title] if title else []
    lines.append(f"{'label':<12} {'n':>6} {'acc':>7}")
    for lab in (order or [k for k in rep if k != "_all"]):
        r = rep[lab]
        lines.append(f"{lab:<12} {r['n']:>6} "
                     + (f"{r['acc']:.3f}" if r["acc"] is not None else "-"))
    r = rep["_all"]
    lines.append(f"{'ALL':<12} {r['n']:>6} {r['acc']:.3f}")
    return "\n".join(lines)


def model_scores(scores: dict) -> str:
    """One line per next-position model: overall and non-stay accuracy."""
    lines = [f"{'model':<12} {'n':>6} {'nonstay':>7} {'acc':>7} {'acc!stay':>8}"]
    for name, s in scores.items():
        nz = f"{s['nonstay']:.3f}" if s["nonstay"] is not None else "-"
        lines.append(f"{name:<12} {s['n']:>6} {s['n_nonstay']:>7} {s['acc']:.3f} {nz:>8}")
    return "\n".join(lines)


def location_scores(area_acc, cell_err, cells_within, per_area, n: int) -> dict:
    """The location report block for one predictor."""
    return {"n": n, "area_accuracy": area_acc, "mean_cell_error": cell_err,
            "within_one_cell": cells_within, "per_area": per_area}
