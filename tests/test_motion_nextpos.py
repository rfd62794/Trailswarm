"""nextpos.py: the 5-class step mapping, count-table model, baselines and adoption rule."""
from __future__ import annotations

import pytest

from pokeagent.vision_motion import nextpos, synthetic, tracks


def test_step_class_mapping_and_exclusions():
    assert nextpos.step_class(0, 0) == "stay"
    assert (nextpos.step_class(1, 0), nextpos.step_class(-1, 0)) == ("right", "left")
    assert (nextpos.step_class(0, 1), nextpos.step_class(0, -1)) == ("down", "up")
    assert nextpos.step_class(1, 1) is None              # diagonal: excluded
    assert nextpos.step_class(2, 0) is None              # >1 tile jump: excluded
    assert nextpos.step_class(0, -3) is None


def test_iter_steps_counts_excluded():
    t = tracks.make_track([(0, 0), (0, 0), (1, 1), (3, 1)] + [(3, 1)] * 6)
    steps = list(nextpos.iter_steps(t))
    assert sum(tgt is None for _, tgt in steps) >= 2     # the diagonal and the jump
    assert all(c[0] and isinstance(c[1], int) for c, _ in steps)


def test_count_table_beats_stay_and_continue_on_patrols():
    train = [synthetic.patrol(70, 6, "x", s, pause=2) for s in range(6)]
    test = [synthetic.patrol(70, 6, "x", s + 1000, pause=2) for s in range(6)]
    model = nextpos.CountTable().fit(s for t in train for s in nextpos.iter_steps(t))
    te = [(c, t) for t in test for c, t in nextpos.iter_steps(t) if t is not None]
    s_tab = nextpos.evaluate(te, model.predict)
    s_stay = nextpos.evaluate(te, nextpos.stay_predict)
    s_cont = nextpos.evaluate(te, nextpos.continue_predict)
    assert s_tab["nonstay"] > s_stay["nonstay"]
    assert s_tab["nonstay"] > s_cont["nonstay"]
    assert set(s_tab) == {"n", "n_nonstay", "acc", "nonstay", "per_class"}
    assert set(s_tab["per_class"]) == set(nextpos.CLASSES) | {"_all"}


def test_continue_baseline_repeats_last_move():
    t = tracks.make_track([(0, 0), (0, 0), (1, 0), (1, 0), (2, 0)])
    ctx = nextpos.context(t, 4)
    assert ctx[2] == "right" and nextpos.continue_predict(ctx) == "right"
    assert nextpos.stay_predict(ctx) == "stay"
    assert nextpos.context(t, 0)[2] == "none"            # track has not moved yet


def test_adoption_rule_needs_margin_and_support():
    assert not nextpos.adopt_neural(0.90, 0.80, 150)     # support short (<200)
    assert not nextpos.adopt_neural(0.815, 0.80, 500)    # margin short (<0.02)
    assert nextpos.adopt_neural(0.83, 0.80, 500)


def test_neural_net_when_torch_present():
    pytest.importorskip("torch")
    from pokeagent.vision_motion import nextpos_net
    train = [synthetic.patrol(70, 6, "x", s, pause=2) for s in range(8)]
    steps = [s for t in train for s in nextpos.iter_steps(t)]
    net = nextpos_net.train_net(steps, seed=0, epochs=8, max_seconds=30)
    te = [(c, t) for c, t in nextpos.iter_steps(synthetic.patrol(70, 6, "x", 99, pause=2))
          if t is not None]
    s = nextpos.evaluate(te, lambda c: nextpos_net.predict(net, c))
    assert s["n"] > 0 and s["nonstay"] > 0.4
