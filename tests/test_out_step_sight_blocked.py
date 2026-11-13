"""Misty gym pocket (2026-11-12): the hold's way out must not be sealed by trainer sight-line temp blocks."""
from types import SimpleNamespace

from pokeagent.explorer.behaviours.plan_goal import PlanGoal

GYM = 0x41


def _ctx(temp):
    visited = {f"{x},5": 1 for x in range(1, 6)}  # a one-lane corridor, the exit warp west of x=1
    gym = {"visited": visited, "warps": {"1,5,LEFT": [0x40, 3, 3]}, "blocked": []}
    outside = {"visited": {"3,3": 1}, "warps": {}, "blocked": []}
    return SimpleNamespace(mem=SimpleNamespace(data={"maps": {str(GYM): gym, "64": outside}}, temp_blocked=temp))


def test_exit_is_found_without_temp_blocks():
    step = PlanGoal._out_step(_ctx({}), GYM, 5, 5, GYM)
    assert step and step[0] == "LEFT"


def test_exit_reachable_only_through_a_sight_blocked_tile_is_still_found():
    ctx = _ctx({(GYM, 3, 5): 10**9})  # a trainer's sight line seals the lane
    step = PlanGoal._out_step(ctx, GYM, 5, 5, GYM)
    assert step and step[0] == "LEFT" and "steps out of the gym" in step[1]


def test_no_exit_known_still_returns_none():
    ctx = _ctx({})
    ctx.mem.data["maps"][str(GYM)]["warps"] = {}
    assert PlanGoal._out_step(ctx, GYM, 5, 5, GYM) is None
