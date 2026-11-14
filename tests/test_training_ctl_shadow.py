"""Training controller slice 1: the shadow derives the six values through existing functions and never changes ctx."""
from __future__ import annotations

import copy

from pokeagent.explorer import training
from pokeagent.explorer.training_ctl import adapters
from pokeagent.explorer.training_ctl.controller import MAX_MISMATCHES, RATE_STEPS, TrainingController
from pokeagent.explorer.training_ctl.state import TrainingState
from test_grind_episode import make_ctx


def test_diff_ignores_unknown_gym_hold_and_reports_real_differences():
    a, b = TrainingState(gym_hold=None, train_need=8), TrainingState(gym_hold=True, train_need=8)
    assert a.diff(b) == {}
    assert TrainingState(train_need=8).diff(TrainingState(train_need=9)) == {"train_need": (8, 9)}


def _no_boss_data(monkeypatch):
    """Pin the 'no boss data' path: boss_party reads local pokered data, present on a dev laptop and absent in the
    cloud, so without this the derived train_member is 0 on one machine and None on the other."""
    monkeypatch.setattr(training, "boss_need_for", lambda goals, party: None)


def test_shadow_equals_old_flags_on_a_quiet_ctx(tmp_path, monkeypatch):
    _no_boss_data(monkeypatch)
    ctx = make_ctx(tmp_path, m=3, lvl=6, need=8)
    ctl = TrainingController()
    assert ctl.observe(ctx) is not None
    assert not ctl.mismatches
    assert ctx.__dict__["training"].diff(adapters.old_flags(ctx)) == {}


def test_observe_never_writes_the_old_flags(tmp_path):
    ctx = make_ctx(tmp_path, m=3, lvl=6, need=8)
    ctx.train_route_live, ctx.train_member = True, 1        # a stale flag the shadow disagrees with
    before = {k: copy.copy(v) for k, v in vars(ctx).items() if k not in ("training", "emu", "mem", "log", "goals", "pos")}
    ctl = TrainingController()
    ctl.observe(ctx)
    assert ("train_route_live" in {f for _, f, _ in ctl.mismatches}) and ctx.train_route_live is True and ctx.train_member == 1
    after = {k: v for k, v in vars(ctx).items() if k in before}
    assert after == before


def test_mismatch_log_is_rate_limited(tmp_path, caplog, monkeypatch):
    _no_boss_data(monkeypatch)
    ctx = make_ctx(tmp_path, m=3, lvl=6, need=8)
    ctx.train_route_live = True
    ctl = TrainingController()
    with caplog.at_level("WARNING"):
        for step in (1, 2, 3, 1 + RATE_STEPS):
            ctx.step = step
            ctl.observe(ctx)
    assert len([r for r in caplog.records if "shadow mismatch" in r.message]) == 2
    assert len(ctl.mismatches) == 4                          # every mismatch is recorded, only the log line is limited


def test_observe_swallows_read_failures(tmp_path):
    ctl = TrainingController()
    assert ctl.observe(object()) is None


def test_mismatches_stay_bounded(tmp_path):
    ctx = make_ctx(tmp_path, m=3, lvl=6, need=8)
    ctx.train_route_live = True
    ctl = TrainingController()
    for step in range(MAX_MISMATCHES * 3):
        ctx.step = step
        ctl.observe(ctx)
    assert len(ctl.mismatches) == MAX_MISMATCHES
    assert ctl.mismatches[-1][0] == MAX_MISMATCHES * 3 - 1      # newest kept


def test_observe_failure_log_is_rate_limited(caplog):
    ctl = TrainingController()
    ctx = type("BadCtx", (), {"step": 0})()                     # no state: every observe raises
    with caplog.at_level("WARNING"):
        for step in (1, 2, 3, 1 + RATE_STEPS):
            ctx.step = step
            assert ctl.observe(ctx) is None
    assert len([r for r in caplog.records if "observe failed" in r.message]) == 2
