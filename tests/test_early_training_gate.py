"""The Brock-level training target must not hold the run on Route 1 before Viridian."""
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.training import before_route2, required_level
from pokeagent.goals import GOALS


def goals_until(last_done: str) -> dict:
    i = GOALS.index(last_done)
    return {g: n <= i for n, g in enumerate(GOALS)}


def test_floor_only_before_route2():
    for last in ("to_route1", "to_viridian", "oaks_parcel", "deliver_parcel"):
        g = goals_until(last)
        assert before_route2(g)
        assert required_level(g, 8, None)[0] == 8


def test_brock_target_from_route2_on():
    for last in ("to_route2", "to_pewter", "to_gym"):
        g = goals_until(last)
        assert not before_route2(g)
        assert required_level(g, 8, None)[0] == 12  # the table value without a party


def test_planner_never_sends_a_weak_lead_back_to_route_1():
    g = {**goals_until("to_viridian"), "_level": 6, "_train_level": 13, "_hp": (20, 20)}
    step = plan_step(g, {}, (0x01, 5, 5), "UP")  # in Viridian, lead L6, a high target
    assert step is None or "back to Route 1" not in step[1]


def test_route2_grinds_in_place_below_the_target_then_goes_on():
    base = {**goals_until("to_route2"), "_level": 9, "_hp": (30, 30)}
    assert plan_step({**base, "_train_level": 13}, {}, (0x0D, 5, 5), "UP") is None  # roam the grass here
