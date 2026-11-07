"""to_bill on Route 24 (2026-11-06): the east-edge push must not lean on a trainer, and Route 25 is not 'back to Route 24'."""
from __future__ import annotations

from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS

BEFORE = {g: True for g in GOALS[:GOALS.index("team_ready") + 1]}  # past the bridge AND the team_ready stage: to_bill is next
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


def test_blocked_cap_counts_one_tile_and_direction_and_resets_on_a_move():
    from pokeagent.explorer import blocked_cap
    streak: dict = {}
    pos = (35, 11, 32)
    assert not any(blocked_cap.note(streak, pos, "UP", False) for _ in range(blocked_cap.BLOCKED_PRESS_CAP - 1))
    assert blocked_cap.note(streak, pos, "UP", False) and not streak  # the cap press fires once, then the streak restarts
    blocked_cap.note(streak, pos, "UP", False)
    blocked_cap.note(streak, pos, "LEFT", False)  # another direction: a new streak
    assert streak == {(pos, "LEFT"): 1}
    blocked_cap.note(streak, pos, "UP", True)
    assert not streak


def test_choose_local_press_into_a_beaten_trainer_blocks_the_tile(tmp_path):
    """Route 24 (2026-11-07): choose_local's reason ('at (x,y) ...') is not 'frontier...'; the rule name must still count as exploring."""
    from pokeagent.explorer.press_frame import PressFrame
    from pokeagent.explorer.press_interact import record_interaction
    from test_item_balls import MAP, PX, PY, ball_sprite, make_ctx
    ctx = make_ctx(tmp_path, memory={MAP: 35, PX: 11, PY: 32})
    ball_sprite(ctx.emu, 9, 11, 31, pic=4)  # the Bug Catcher on the bridge, one tile above
    ctx.deciding_rule = "frontier"
    record_interaction(ctx, PressFrame("UP", "agent", "at (11,32) blocked=['RIGHT']; UP leads to a tile seen 0x",
                                       before=(35, 11, 32), after=(35, 11, 32)))
    assert (35, 11, 31) in ctx.mem.temp_blocked
    assert "11,32,UP" not in ctx.mem.m(35)["blocked"]


def test_capped_blocked_presses_temp_block_the_tile_even_without_a_visible_person(tmp_path):
    from pokeagent.explorer import blocked_cap
    from pokeagent.explorer.press_frame import PressFrame
    from pokeagent.explorer.press_interact import record_interaction
    from test_item_balls import MAP, PX, PY, make_ctx
    ctx = make_ctx(tmp_path, memory={MAP: 35, PX: 11, PY: 32})
    ctx.frontier_route, ctx.frontier_target, ctx.frontier_at = ["UP"], (35, 11, 20), (35, 11, 32)
    for _ in range(blocked_cap.BLOCKED_PRESS_CAP):
        record_interaction(ctx, PressFrame("UP", "agent", "plan_goal: north", before=(35, 11, 32), after=(35, 11, 32)))
    assert (35, 11, 31) in ctx.mem.temp_blocked and ctx.frontier_route == []


def test_a_person_tile_is_not_a_frontier_side(tmp_path):
    """Route 24 bridge (2026-11-07): the frontier tile whose only unexplored side is a beaten trainer's tile sent the agent
    (11,33) <-> (11,32) forever, because the trainer's tile is never 'visited'."""
    mem = MapMemory(tmp_path / "maps.json")
    mem.visit(0x23, 11, 33, 1); mem.visit(0x23, 11, 32, 1)
    for y in (32, 33):  # a one-wide corridor: walls both sides, the south end already walked
        mem.m(0x23)["blocked"] += [f"11,{y},LEFT", f"11,{y},RIGHT"]
    mem.m(0x23)["blocked"].append("11,33,DOWN")
    assert mem.is_frontier((0x23, 11, 32))  # (11,31) was never visited
    mem.temp_blocked[(0x23, 11, 31)] = 10**9
    assert not mem.is_frontier((0x23, 11, 32))
    mem.temp_blocked.clear()
    mem.m(0x23)["npcs"] = {"slot7:pic4": {"pic": 4, "last": [11, 31], "moves": False}}
    assert not mem.is_frontier((0x23, 11, 32))
