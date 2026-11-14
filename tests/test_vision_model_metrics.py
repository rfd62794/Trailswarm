"""evaluate: overall/macro/coarse/per-class, confusions, weighted, unseen-in-train."""
from __future__ import annotations

import numpy as np

from pokeagent.vision_model import data, metrics


def test_scoring_and_unseen():
    names = ["sprite:1", "sprite:2", "tile:3", "ghost:9"]
    true = np.array([0, 0, 0, 1, 1, 2])
    pred = np.array([0, 0, 1, 1, 1, 2])
    tco = np.array([0, 0, 0, 1, 1, 4])
    pco = np.array([0, 0, 1, 1, 1, 4])
    rep = metrics.evaluate(pred, true, pco, tco, names, train_classes={0, 1},
                           coarse_names=data.COARSE)
    assert rep["overall"] == 5 / 6
    assert rep["coarse"] == 5 / 6
    assert rep["per_class"]["sprite:1"] == {"support": 3, "acc": 2 / 3,
                                           "wacc": 2 / 3}
    assert rep["per_class"]["ghost:9"]["support"] == 0
    assert rep["macro"] == (2 / 3 + 1.0 + 1.0) / 3     # zero-support class excluded
    assert rep["top_confusions"] == [["sprite:1", "sprite:2", 1]]
    assert rep["unseen_in_train"] == 1                 # class 2 never trained on
    assert rep["coarse_per_class"]["enemy"] == {"support": 3, "acc": 2 / 3}


def test_weighted_accuracy():
    names = ["a", "b"]
    true = np.array([0, 0, 1])
    pred = np.array([0, 1, 1])
    w = np.array([10.0, 1.0, 1.0])
    rep = metrics.evaluate(pred, true, true.copy(), true.copy(), names, weight=w)
    assert rep["overall"] == 2 / 3
    assert rep["overall_weighted"] == 11 / 12
    assert rep["per_class"]["a"]["wacc"] == 10 / 11
