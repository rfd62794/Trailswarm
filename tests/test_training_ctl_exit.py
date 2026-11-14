"""Training controller slice 5a (Exit): the two gym-hold flags (``ctx.gym_hold_seen``, the ``(step, bool)``
stamp, and ``ctx.__dict__["floor_unmet"]``) have one writer module and one reader set, with the exact values
and timing main used. ROM-free; the empty-ledger invariant is pinned at the bottom.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from pokeagent.explorer.behaviours import plan_goal
from pokeagent.explorer.training_ctl import exit_rule


def _ctx(step=0):
    return SimpleNamespace(step=step, __dict__={})


def test_publish_hold_stamps_the_step_with_a_bool():
    ctx = _ctx(step=42)
    exit_rule.publish_hold(ctx, 1)
    assert ctx.gym_hold_seen == (42, True)          # truthy input is coerced, as bool(hold) did
    exit_rule.publish_hold(ctx, False)
    assert ctx.gym_hold_seen == (42, False)


def test_publish_floor_round_trips_and_defaults_false():
    ctx = _ctx()
    assert exit_rule.floor_unmet(ctx) is False                       # never published: False
    exit_rule.publish_floor(ctx, 1)
    assert ctx.__dict__["floor_unmet"] is True
    assert exit_rule.floor_unmet(ctx) is True
    exit_rule.publish_floor(ctx, False)
    assert ctx.__dict__["floor_unmet"] is False
    assert exit_rule.floor_unmet(ctx) is False


def test_hold_clear_is_goal_talks_rule_verbatim():
    ctx = _ctx(step=100)
    assert exit_rule.hold_clear(ctx, 30) is False                    # never stamped: the gate stays shut
    ctx.gym_hold_seen = (100, True)
    assert exit_rule.hold_clear(ctx, 30) is False                    # stamped held
    ctx.gym_hold_seen = (100, False)
    assert exit_rule.hold_clear(ctx, 30) is True                     # judged clear this step
    ctx.step = 130
    assert exit_rule.hold_clear(ctx, 30) is True                     # exactly `fresh` steps old still counts
    ctx.step = 131
    assert exit_rule.hold_clear(ctx, 30) is False                    # stale: PlanGoal must judge again


def test_floor_hold_matches_the_old_frontier_expression():
    """Oracle: the pre-move frontier line, verbatim - every floor_unmet x stamped-hold combination."""
    for unmet in (True, False):
        for seen in ((50, True), (50, False), None):
            ctx = _ctx(step=100)
            exit_rule.publish_floor(ctx, unmet)
            if seen is not None:
                ctx.gym_hold_seen = seen
            old = bool(ctx.__dict__.get("floor_unmet")) and (getattr(ctx, "gym_hold_seen", None) or (0, False))[1]
            assert exit_rule.floor_hold(ctx) == old
    ctx = _ctx(step=100)                                             # neither flag ever stamped
    assert exit_rule.floor_hold(ctx) is False


def test_old_writers_are_gone():
    """The flags are assigned only in exit_rule.py; the shadow (adapters.py) reads them raw on purpose."""
    from pokeagent.explorer import training
    from pokeagent.explorer.behaviours import frontier, goal_talk
    for mod in (plan_goal, training, goal_talk, frontier):
        src = inspect.getsource(mod)
        assert "gym_hold_seen =" not in src, mod.__name__
        assert '__dict__["floor_unmet"]' not in src, mod.__name__
        assert '.get("floor_unmet"' not in src, mod.__name__
