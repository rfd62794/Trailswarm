"""Next-position prediction: the 5-class displacement H samples ahead, baselines + count table."""
from __future__ import annotations

import numpy as np

from pokeagent.vision_motion.report import accuracy, per_class
from pokeagent.vision_motion.tracks import dwell_at

H, LOOKBACK = 2, 4
CLASSES = ("stay", "up", "down", "left", "right")
JUMP = "jump"    # context-only bucket for diagonal/multi-tile steps
NONE = "none"    # context-only: the track has not displaced yet
SYMBOLS = CLASSES + (JUMP,)


def step_class(dx: int, dy: int) -> str | None:
    """Displacement -> class; a diagonal or a jump of more than one tile -> None (excluded)."""
    if dx == 0 and dy == 0:
        return "stay"
    if (dx and dy) or abs(dx) > 1 or abs(dy) > 1:
        return None
    return "right" if dx > 0 else "left" if dx else ("down" if dy > 0 else "up")


def last_move(track, t: int) -> str:
    """The last non-stay displacement class at or before sample ``t`` (a displacement is a
    tile change; staying produces none), or ``NONE`` if the track never moved."""
    for j in range(t, 0, -1):
        d = step_class(track[j]["x"] - track[j - 1]["x"],
                       track[j]["y"] - track[j - 1]["y"])
        if d is None:
            return JUMP
        if d != "stay":
            return d
    return NONE


def context(track, t: int, lookback: int = LOOKBACK):
    """``(disps, dwell, move)`` at sample ``t``: the last ``lookback`` single-sample
    displacement classes (padded ``"stay"``), the dwell bucket 0/1/2/3+ (samples already
    spent on the current tile), and the last non-stay displacement class."""
    disps = tuple("stay" if j <= 0 else
                  step_class(track[j]["x"] - track[j - 1]["x"],
                             track[j]["y"] - track[j - 1]["y"]) or JUMP
                  for j in range(t - lookback + 1, t + 1))
    return disps, min(dwell_at(track, t) - 1, 3), last_move(track, t)


def iter_steps(track, h: int = H):
    """``(context, target)`` per scored step; ``target`` is None for excluded steps
    (diagonal or >1 tile); the caller counts them."""
    for t in range(1, len(track) - h):
        yield context(track, t), step_class(track[t + h]["x"] - track[t]["x"],
                                            track[t + h]["y"] - track[t]["y"])


def stay_predict(ctx) -> str:
    return "stay"


def continue_predict(ctx) -> str:
    """Repeat the last non-stay, non-jump displacement of the track so far; else ``stay``."""
    return ctx[2] if ctx[2] in CLASSES[1:] else "stay"


class CountTable:
    """``P(next | last displacement, dwell bucket)`` with back-off to
    ``P(next | last displacement)`` then to the class prior; Laplace smoothing ``smooth``.
    A level applies only when it holds at least ``min_count`` train steps."""
    def __init__(self, smooth: float = 1.0, min_count: int = 5):
        self.smooth, self.min_count = smooth, min_count
        self.t1, self.t2, self.prior = {}, {}, {}

    def fit(self, steps):
        self.prior = {c: 0 for c in CLASSES}
        for (_, dwell, move), tgt in steps:
            if tgt is not None:
                self.t1.setdefault((move, dwell), {c: 0 for c in CLASSES})[tgt] += 1
                self.t2.setdefault(move, {c: 0 for c in CLASSES})[tgt] += 1
                self.prior[tgt] += 1
        return self

    def _row(self, ctx):
        _, dwell, move = ctx
        for row in (self.t1.get((move, dwell)), self.t2.get(move)):
            if row is not None and sum(row.values()) >= self.min_count:
                return row
        return self.prior

    def probs(self, ctx) -> dict:
        row = self._row(ctx)
        tot = sum(row.values()) + self.smooth * len(CLASSES)
        return {c: (row.get(c, 0) + self.smooth) / tot for c in CLASSES}
    def predict(self, ctx) -> str:
        p = self.probs(ctx)
        return max(CLASSES, key=lambda c: p[c])

    def prob_nonstay(self, ctx) -> float:
        return 1.0 - self.probs(ctx)["stay"]


def encode(ctx) -> np.ndarray:
    """One-hot of the last-4 displacement classes (6 symbols) + dwell bucket (4): 28 dims."""
    disps, dwell, _ = ctx
    v = np.zeros(len(SYMBOLS) * LOOKBACK + 4, dtype=np.float32)
    for i, d in enumerate(disps):
        v[i * len(SYMBOLS) + SYMBOLS.index(d)] = 1.0
    v[len(SYMBOLS) * LOOKBACK + dwell] = 1.0
    return v


def evaluate(steps, predict) -> dict:
    """Score a predictor on ``(ctx, target)`` steps: overall accuracy, accuracy over the
    non-``stay`` steps, supports, and the per-class table."""
    truth = [t for _, t in steps]
    pred = [predict(c) for c, _ in steps]
    nz = [i for i, t in enumerate(truth) if t != "stay"]
    return {"n": len(truth), "n_nonstay": len(nz),
            "acc": accuracy(truth, pred),
            "nonstay": (sum(pred[i] == truth[i] for i in nz) / len(nz)) if nz else None,
            "per_class": per_class(truth, pred, CLASSES)}


def adopt_neural(net_nonstay: float, table_nonstay: float, n_nonstay: int,
                 margin: float = 0.02, min_n: int = 200) -> bool:
    """Adoption rule: neural adopted only if its non-stay accuracy beats the count table by
    >= ``margin`` on at least ``min_n`` held-out non-stay steps."""
    return (n_nonstay >= min_n and net_nonstay is not None
            and table_nonstay is not None and net_nonstay >= table_nonstay + margin)
