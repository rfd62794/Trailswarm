"""A start state with no goals sidecar and no goal name: every goal before the latest RAM-true one is assumed done (seen at Bill's house)."""
from types import SimpleNamespace

from pokeagent.explorer import press_goals
from pokeagent.goals import GOALS


def _ctx(tmp_path):
    return SimpleNamespace(emu=None, initial_goals=set(), initial_goals_ready=False, run_dir=tmp_path, log=lambda *a, **k: None,
                           opts=SimpleNamespace(state_stem="88_2_7", state_path=""))


def test_prefix_before_latest_true_goal_is_assumed_done(tmp_path, monkeypatch):
    state = {g: False for g in GOALS}
    state["to_bill"] = True                                   # RAM shows only the late goal; potion / to_route1 have no way to show
    monkeypatch.setattr(press_goals, "check_goals", lambda emu, ctx: dict(state))
    ctx = _ctx(tmp_path)
    press_goals.seed_initial_goals(ctx)
    assert set(GOALS[:GOALS.index("to_bill") + 1]) <= ctx.initial_goals
    assert "ss_ticket" not in ctx.initial_goals


def test_nothing_true_assumes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(press_goals, "check_goals", lambda emu, ctx: {g: False for g in GOALS})
    ctx = _ctx(tmp_path)
    press_goals.seed_initial_goals(ctx)
    assert ctx.initial_goals == set()
