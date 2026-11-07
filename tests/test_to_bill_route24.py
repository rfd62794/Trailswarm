"""to_bill on Route 24 (2026-11-06): the east-edge push must not lean on a trainer, and Route 25 is not 'back to Route 24'."""
from __future__ import annotations

from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS

BEFORE = {g: True for g in GOALS[:GOALS.index("nugget_bridge") + 1]}
GOALS_NOW = {**BEFORE, "_hp": (40, 40), "_level": 30, "_train_level": 8}


def _bridge(tmp_path, east_warp: bool):
    """Route 24: bridge column x=10 (y 8..12); water east of every tile but (10,10) and (10,8); optional learned east connection."""
    mem = MapMemory(tmp_path / "maps.json")
    for y in range(8, 13):
        mem.visit(0x23, 10, y, 1)
    for y in (9, 11, 12):
        mem.m(0x23)["blocked"].append(f"10,{y},RIGHT")
    if east_warp:
        for x in range(11, 20):
            mem.visit(0x23, x, 8, 1)
        mem.m(0x23)["warps"]["19,8,RIGHT"] = [0x24, 0, 8]
        mem.visit(0x24, 0, 8, 1)
    return mem.data["maps"]


def test_edge_push_skips_a_tile_next_to_a_trainer(tmp_path):
    maps = _bridge(tmp_path, east_warp=False)
    # without the trainer (10,10) is the nearest open tile: push RIGHT
    step = plan_step({**GOALS_NOW, "_sprites": []}, maps, (0x23, 10, 10), "UP")
    assert step and step[0] == "RIGHT" and "pushing RIGHT" in step[1]
    # a trainer stands at (11,10): leaning on him never ends, so head for the next open tile
    step = plan_step({**GOALS_NOW, "_sprites": [(7, 11, 10)]}, maps, (0x23, 10, 10), "UP")
    assert step and step[0] == "UP" and "known tile (10,8)" in step[1], step


def test_learned_east_connection_is_walked_to(tmp_path):
    maps = _bridge(tmp_path, east_warp=True)
    step = plan_step({**GOALS_NOW, "_sprites": [(7, 11, 10)]}, maps, (0x23, 10, 12), "UP")
    assert step and step[0] == "UP" and "Route 25" in step[1], step


def test_route_25_is_left_to_exploration(tmp_path):
    maps = _bridge(tmp_path, east_warp=True)
    assert plan_step({**GOALS_NOW, "_sprites": []}, maps, (0x24, 5, 8), "RIGHT") is None


def test_frontier_press_into_a_person_blocks_that_tile_and_replans(tmp_path):
    """Route 25 (2026-11-06): a beaten trainer stands on a frontier route; pressing into him must route around, not repeat."""
    from pokeagent.explorer.press_frame import PressFrame
    from pokeagent.explorer.press_interact import record_interaction
    from test_item_balls import MAP, PX, PY, ball_sprite, make_ctx
    ctx = make_ctx(tmp_path, memory={MAP: 36, PX: 13, PY: 6})
    ball_sprite(ctx.emu, 9, 13, 7, pic=14)  # the hiker, one tile below
    ctx.frontier_route, ctx.frontier_target, ctx.frontier_at = ["DOWN"], (36, 13, 9), (36, 13, 6)
    record_interaction(ctx, PressFrame("DOWN", "agent", "frontier: 3 steps to (13,9)", before=(36, 13, 6), after=(36, 13, 6)))
    assert (36, 13, 7) in ctx.mem.temp_blocked and ctx.frontier_route == [] and ctx.frontier_target is None
    assert "13,6,DOWN" not in ctx.mem.m(36)["blocked"]  # a person is never a wall
    # a non-exploring press (walking to a nurse) leaves routing alone
    ctx.mem.temp_blocked.clear()
    record_interaction(ctx, PressFrame("DOWN", "agent", "plan_goal: to the nurse", before=(36, 13, 6), after=(36, 13, 6)))
    assert not ctx.mem.temp_blocked
