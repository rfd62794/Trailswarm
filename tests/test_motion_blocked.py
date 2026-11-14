"""blocked.py: the synthetic blocked-corridor fixture and its hard bounds."""
from __future__ import annotations

from pokeagent.vision_motion import blocked, nextpos, synthetic


def test_flag_blocked_on_a_single_track():
    train = [synthetic.patrol(70, 6, "x", s) for s in range(10)]
    train += [synthetic.stationary(70) for _ in range(5)]
    model = nextpos.CountTable().fit(s for t in train for s in nextpos.iter_steps(t))
    t = synthetic.patrol_blocked(70, 6, "x", block_at=30, seed=3)
    i = blocked.flag_blocked(t, model)
    assert i is not None and i - 30 <= 8                # window + 2 samples after the block
    assert blocked.flag_blocked(synthetic.stationary(70), model) is None
    assert blocked.flag_blocked(synthetic.patrol(70, 6, "x", 1), model) is None


def test_blocked_fixture_meets_its_bounds():
    r = blocked.blocked_report(seed=1)
    assert r["detection_rate"] >= 0.90
    assert r["median_delay"] <= r["window"] + 2
    for kind, rate in r["false_positive_rate"].items():
        assert rate < 0.05, kind
    assert set(r["false_positive_rate"]) == {"patrol", "paused", "stationary", "wandering"}
