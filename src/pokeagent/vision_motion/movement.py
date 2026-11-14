"""Movement-type labels from the RAM move byte, and a depth<=3 threshold-rule classifier.
Labels are provisional: the 0xC206 NPC move byte is unverified in ram_map.json."""
from __future__ import annotations

import numpy as np

from pokeagent.vision_motion.features import collinear, reversals

STAY, WALK = 0xFF, 0xFE
MIN_ROWS = 6
LABELS = ("stationary", "wandering", "patrolling")


def label_track(track) -> str | None:
    """RAM-byte label: every row 0xFF -> ``"stationary"``; every row 0xFE -> walking, which is
    ``"patrolling"`` when the whole-track trajectory is collinear with >=2 distinct tiles and
    >=2 direction reversals, else ``"wandering"``. Any other move value, a mixed track or a
    track shorter than MIN_ROWS -> ``None`` (excluded)."""
    if len(track) < MIN_ROWS:
        return None
    moves = {r["move"] for r in track}
    if moves == {STAY}:
        return "stationary"
    if moves != {WALK}:
        return None
    if collinear(track) and len({(r["x"], r["y"]) for r in track}) >= 2 and reversals(track) >= 2:
        return "patrolling"
    return "wandering"


def walking_label(label: str) -> str:
    """The pure-RAM binary truth: stationary vs walking (wandering + patrolling merged)."""
    return "stationary" if label == "stationary" else "walking"


class Majority:
    """Baseline: always predicts the most frequent train label."""

    def fit(self, x, y):
        vals, counts = np.unique(np.asarray(y), return_counts=True)
        self.label_ = str(vals[counts.argmax()])
        return self

    def predict(self, x):
        return [self.label_] * len(x)


class RuleTree:
    """Greedy threshold-rule tree of depth <= ``depth``. Each node takes the single
    (feature, threshold) split that maximises train accuracy; leaves predict the node
    majority. Pure numpy, no libraries."""

    def __init__(self, depth: int = 3):
        self.depth = depth

    def fit(self, x, y):
        self.root_ = self._node(np.asarray(x, float), np.asarray(y), 0)
        return self

    def _node(self, x, y, depth) -> dict:
        vals, counts = np.unique(y, return_counts=True)
        node = {"label": str(vals[counts.argmax()])}
        if depth >= self.depth or len(vals) == 1:
            return node
        best = self._best_split(x, y, counts.max())
        if best is None:
            return node
        f, thr, left = best
        node.update(f=f, thr=thr,
                    lo=self._node(x[left], y[left], depth + 1),
                    hi=self._node(x[~left], y[~left], depth + 1))
        return node

    @staticmethod
    def _best_split(x, y, base):
        best = None
        best_score = base  # majority count; only a strict improvement splits
        for f in range(x.shape[1]):
            col = x[:, f]
            uniq = np.unique(col)
            for thr in (uniq[:-1] + uniq[1:]) / 2:
                left = col <= thr
                score = np.unique(y[left], return_counts=True)[1].max() \
                    + np.unique(y[~left], return_counts=True)[1].max()
                if score > best_score:
                    best_score, best = score, (f, float(thr), left)
        return best

    def predict(self, x):
        return [self._one(row) for row in np.asarray(x, float)]

    def _one(self, row):
        node = self.root_
        while "f" in node:
            node = node["lo"] if row[node["f"]] <= node["thr"] else node["hi"]
        return node["label"]


def thresholds(tree: RuleTree) -> list:
    """The chosen (feature index, threshold) splits, for the report."""
    out = []

    def walk(node):
        if "f" in node:
            out.append((node["f"], node["thr"]))
            walk(node["lo"])
            walk(node["hi"])

    walk(tree.root_)
    return out
