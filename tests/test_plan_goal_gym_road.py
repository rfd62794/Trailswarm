"""The gym hold owns the road: a planner push toward the stage boss never enters the gym while not ready."""
from pokeagent.explorer.behaviours.plan_goal import PlanGoal


def test_stage_boss_push_counts_as_the_gym_road():
    # Cerulean 2026-11-12: "goal beat_misty: N steps toward it" walked in, the hold walked out, repeat
    assert PlanGoal._gym_road(("UP", "goal beat_misty: 4 steps toward it over the learned world"), "beat_misty")
    assert PlanGoal._gym_road(("UP", "goal gym: walking in"), None)
    assert not PlanGoal._gym_road(("UP", "goal beat_misty: 4 steps toward it"), "beat_brock")
    assert not PlanGoal._gym_road(("UP", "heal: 4 steps to a Pokecenter"), "beat_misty")
    assert not PlanGoal._gym_road(None, "beat_misty")
