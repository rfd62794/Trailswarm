"""movement.py: RAM-byte labels, the trajectory patrol/wander split, the rule classifier."""
from __future__ import annotations

import numpy as np

from pokeagent.vision_motion import features, movement, report, split, synthetic, tracks


def test_label_track_ram_rules():
    assert movement.label_track(synthetic.stationary(10)) == "stationary"
    assert movement.label_track(synthetic.stationary(5)) is None          # under 6 rows
    t = synthetic.stationary(10)
    t[3]["move"] = 0x12
    assert movement.label_track(t) is None                                # other move byte
    t[3]["move"] = 254
    assert movement.label_track(t) is None                                # mixed 255/254
    assert movement.label_track(synthetic.patrol(50, 5, "x", 0)) == "patrolling"
    assert movement.label_track(synthetic.wandering(50, 0)) == "wandering"


def test_patrolling_needs_collinear_tiles_and_two_reversals():
    one_reversal = tracks.make_track(
        [(0, 0), (1, 0), (2, 0), (3, 0), (2, 0), (1, 0), (0, 0)], move=254)
    assert movement.reversals(one_reversal) == 1
    assert movement.label_track(one_reversal) == "wandering"
    two_reversals = tracks.make_track([(0, 0), (1, 0)] * 4, move=254)
    assert movement.reversals(two_reversals) >= 2
    assert movement.label_track(two_reversals) == "patrolling"
    two_d = tracks.make_track([(0, 0), (1, 0), (1, 1), (0, 1)] * 3, move=254)
    assert movement.label_track(two_d) == "wandering"                     # not collinear


def test_features_look_only_at_the_first_24_rows():
    t = synthetic.patrol(80, 5, "x", 0)
    assert (features.features(t) == features.features(t[:24])).all()


def test_late_starting_patrol_is_a_legitimate_hard_case():
    pos = [(5, 5)] * 24 + [(6, 5), (7, 5), (6, 5), (5, 5)] * 4
    t = tracks.make_track(pos, move=254)
    assert movement.label_track(t) == "patrolling"          # whole-track trajectory label
    f = features.features(t)
    assert f[0] == 1.0 and f[1] == 0.0                       # window looks stationary


def _labeled(ts):
    out = [(features.features(t), movement.label_track(t)) for t in ts.values()]
    return [(x, y) for x, y in out if y]


def test_rule_tree_beats_majority_on_a_synthetic_mix():
    train, test = split.split_tracks_by_area(synthetic.dataset(0), seed=0)
    tr = _labeled(train)
    te = _labeled(test)
    clf = movement.RuleTree().fit([x for x, _ in tr], [y for _, y in tr])
    maj = movement.Majority().fit([x for x, _ in tr], [y for _, y in tr])
    truth = [y for _, y in te]
    pred = clf.predict(np.stack([x for x, _ in te]))
    pred_m = maj.predict(np.stack([x for x, _ in te]))
    rep = report.per_class(truth, pred, movement.LABELS)
    rep_m = report.per_class(truth, pred_m, movement.LABELS)
    assert rep["_all"]["acc"] > rep_m["_all"]["acc"]
    for lab in movement.LABELS:
        assert set(rep[lab]) == {"n", "acc"}
    binary = report.per_class([movement.walking_label(t) for t in truth],
                              [movement.walking_label(p) for p in pred],
                              ("stationary", "walking"))
    assert binary["_all"]["acc"] >= 0.9                      # the RAM-truth headline
    assert set(binary) == {"stationary", "walking", "_all"}
