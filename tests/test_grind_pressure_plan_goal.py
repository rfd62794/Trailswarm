"""plan_goal's grind-pressure consumption: the latch thresholds, the boss-distance term and the
grind/gym-hold decision helpers. All contexts are synthetic (no ROM, no emulator).
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import plan_goal
from pokeagent.explorer.behaviours.plan_goal import PlanGoal
from pokeagent.knowledge import team_plan


def _ctx(stage_goal="beat_misty", maps=None):
    return SimpleNamespace(stage_goal=stage_goal,
                           mem=SimpleNamespace(data={"maps": maps or {}}, temp_blocked={}))


def test_boss_gap_counts_learned_steps_to_the_gym():
    # map 0x03 tile (2,4) UP is a learned warp onto Misty's gym (0x41): the boss is one step away
    ctx = _ctx(maps={"3": {"visited": {"2,4": 1}, "warps": {"2,4,UP": [65, 5, 5]}}})
    assert PlanGoal._boss_gap(ctx, 0x03, 2, 4) == 1


def test_boss_gap_unknown_is_far_not_urgent():
    ctx = _ctx(maps={})
    assert PlanGoal._boss_gap(ctx, 0x03, 2, 4) == team_plan.NEAR_STEPS
    # a stage with no gym map reads the same as "far away"
    assert PlanGoal._boss_gap(_ctx(stage_goal="to_route3"), 0x0E, 5, 5) == team_plan.NEAR_STEPS


def test_enters_detects_a_planned_press_into_the_gym():
    ctx = _ctx(maps={"3": {"visited": {"2,4": 1}, "warps": {"2,4,UP": [65, 5, 5]}}})
    assert PlanGoal._enters(ctx, 0x03, 2, 4, ("UP", "goal beat_misty: 1 steps"), 0x41)
    assert not PlanGoal._enters(ctx, 0x03, 2, 4, ("DOWN", "goal beat_misty: 1 steps"), 0x41)
    assert not PlanGoal._enters(ctx, 0x03, 2, 4, ("A", "goal beat_misty: at the door"), 0x41)


def test_grind_step_uses_train_route_until_grind_episode_lands(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(plan_goal.train_route, "step", lambda maps, pos, blocked, hp, mx: ("UP", "to Route 24 grass"))
    assert PlanGoal._grind_step(ctx, 0x03, 2, 4, 30, 40) == ("UP", "to Route 24 grass")
    monkeypatch.setattr(plan_goal.train_route, "step", lambda maps, pos, blocked, hp, mx: None)
    assert PlanGoal._grind_step(ctx, 0x03, 2, 4, 30, 40) is None


def test_pressure_thresholds_bound_the_latch():
    assert team_plan.GRIND_PRESSURE_START > team_plan.GRIND_PRESSURE_STOP > 0
    team = [SimpleNamespace(level=10) for _ in range(4)]
    p = team_plan.grind_pressure(team, 25, next_boss_gap_steps=5, blackouts_recent=2,
                                 breakers=(1, 2, 3), lead_level=10)
    assert p >= team_plan.GRIND_PRESSURE_START     # a big weak team at the boss's door grinds
    p0 = team_plan.grind_pressure(team, 10, lead_level=10)
    assert p0 < team_plan.GRIND_PRESSURE_STOP      # no gap, no breakers: the latch releases
