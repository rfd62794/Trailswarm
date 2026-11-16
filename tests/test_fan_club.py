"""Marathon 2026-11-16a: after Cut the stage pokemon_fan_club had no target, planner step, patrol exit or talk: 8,000 steps in the Old Rod house (0xA3)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent.explorer import cerulean_south, fan_club as fc, patrol_exit, planner_east, route5_vermilion as rv
from pokeagent.explorer.behaviours import goal_talk
from pokeagent.explorer.behaviours.goal_talk import GoalTalk
from pokeagent.goals import GOALS

ROM = Path(__file__).resolve().parents[1] / "roms" / "Pokemon Red.gb"
G = SimpleNamespace(path=lambda pos, goal: None, blocked_now=frozenset())


def _goals(upto):
    return {g: True for g in GOALS[:GOALS.index(upto)]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)


def _asking(answer=("UP",)):
    asked = []

    def plan(start, goals, walls=None, blocked=None, hard=None):
        asked.append(set(goals))
        return list(answer)
    return plan, asked


def test_every_stage_after_cut_has_a_map_target():
    for stage, m in (("pokemon_fan_club", 0x5A), ("bike_voucher", 0x5A), ("bike_shop", 0x42), ("bicycle", 0x42)):
        assert planner_east.TARGETS[stage]((m, 1, 1)) and not planner_east.TARGETS[stage]((0xA3, 1, 1))


def test_vermilion_walks_to_the_fan_club_door():
    plan, asked = _asking(("LEFT",))
    out = planner_east.east_road_step(G, {}, {**_goals("pokemon_fan_club"), "_route_plan": plan}, (fc.VERMILION, 20, 10))
    assert out and out[0] == "LEFT" and "Fan Club door" in out[1] and asked == [{fc.FAN_DOOR}]


def test_inside_the_fan_club_the_voucher_stage_is_a_talk_not_a_route():
    plan, asked = _asking()
    assert planner_east.east_road_step(G, {}, {**_goals("bike_voucher"), "_route_plan": plan}, (fc.FAN_CLUB, 3, 6)) is None and not asked


def test_after_the_voucher_the_way_back_leaves_the_club_then_vermilion_by_its_north_edge():
    plan, asked = _asking()
    goals = {**_goals("bike_shop"), "_route_plan": plan}
    assert planner_east.east_road_step(G, {}, goals, (fc.FAN_CLUB, 3, 7))[0] == "DOWN"
    planner_east.east_road_step(G, {}, goals, (fc.VERMILION, 9, 14))
    assert asked[-1] == fc.VERMILION_TOP
    assert planner_east.east_road_step(G, {}, goals, (fc.VERMILION, 25, 0))[0] == "UP"


def test_route6_path_route5_and_cerulean_each_chain_to_the_next_goal():
    plan, asked = _asking()
    goals = {**_goals("bike_shop"), "_route_plan": plan}
    for pos, want in (((rv.ROUTE6, 14, 30), fc.HOUSE_5_EXIT), ((rv.PATH_NS, 2, 40), fc.HOUSE_5_EXIT), ((rv.ROUTE5, 16, 20), fc.ROUTE5_TOP),
                      ((cerulean_south.CERULEAN, 20, 33), {fc.BIKE_DOOR})):
        asked.clear()
        assert planner_east.east_road_step(G, {}, goals, pos)[0] == "UP" and asked == [want], pos
    assert planner_east.east_road_step(G, {}, goals, (rv.PATH_5, 3, 7))[0] == "DOWN"


def test_old_rod_house_is_left_by_its_learned_exit_while_the_fan_club_is_the_target(tmp_path, monkeypatch):
    from pokeagent.explorer.memory import MapMemory
    from pokeagent.ramworld import MapHeader
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"]["163"] = {"visited": {"4,6": 1, "4,5": 1}, "warps": {"4,6,DOWN": [5, 7, 4]}}
    mem.data["maps"]["5"] = {"visited": {"7,4": 1}}
    monkeypatch.setattr(patrol_exit, "read_map_header", lambda emu: MapHeader(12, 4, 4, (), (), ()))
    c = SimpleNamespace(emu=None, mem=mem, stage_goal="pokemon_fan_club", center_intent=None, step=100)
    assert patrol_exit.exit_step(c, 0xA3, 4, 5)[0] == "DOWN"


def _ctx(goals, m, x, y, facing="UP"):
    return SimpleNamespace(goals=lambda: goals, view=SimpleNamespace(m=m, x=x, y=y, box=False, battling=False), proc=None, facing=facing,
                           goal_talk_tries={}, mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()), log=lambda *a, **k: None)


def test_the_chairman_is_talked_to_until_the_voucher_is_in_the_bag():
    stand = goal_talk.GOAL_TALKS["bike_voucher"]
    assert stand[0] == fc.FAN_CLUB and goal_talk.TALK_CAPS["bike_voucher"] > goal_talk.MAX_TALKS
    c = _ctx({"bike_voucher": False}, 0x5A, stand[1], stand[2], stand[3])
    assert GoalTalk().applies(c) and GoalTalk().step(c).button == "A"
    assert not GoalTalk().applies(_ctx({"bike_voucher": True}, 0x5A, 2, 1))
    assert not GoalTalk().applies(_ctx({"bike_voucher": False}, 0xA3, 2, 1))


def test_the_clerk_is_talked_to_only_with_the_voucher_goal_met():
    assert not GoalTalk().applies(_ctx({"bike_voucher": False, "bicycle": False}, 0x42, 4, 2, "RIGHT"))
    assert GoalTalk().applies(_ctx({"bike_voucher": True, "bicycle": False}, 0x42, 4, 2, "RIGHT"))


def test_the_campaign_detectors_match_the_items_and_maps():
    import json
    d = json.loads((Path(__file__).resolve().parents[1] / "src/pokeagent/data/campaign.json").read_text(encoding="utf-8"))
    rows = {r["id"]: r["detector"] for r in d["goals"]}
    assert rows["pokemon_fan_club"] == {"map": [fc.FAN_CLUB]} and rows["bike_voucher"] == {"item": 45}
    assert rows["bike_shop"]["map_now_with_item"] == {"map": [fc.BIKE_SHOP], "item": 45} and rows["bicycle"] == {"item": 6}


@pytest.mark.skipif(not ROM.exists(), reason="needs the ROM")
def test_rom_routes_reach_the_fan_club_and_back_to_the_bike_shop():
    from pokeagent.atlas.walkgrid import rom_cave_planner
    plan = rom_cave_planner(str(ROM), maps=fc.PLANNER_MAPS)
    assert plan.warp_tiles(fc.VERMILION, fc.FAN_CLUB) == {fc.FAN_DOOR} and plan.warp_tiles(fc.CERULEAN, fc.BIKE_SHOP) == {fc.BIKE_DOOR}
    assert plan((fc.VERMILION, 18, 25), {fc.FAN_DOOR})
    for start, goals in (((fc.FAN_CLUB, 3, 6), fc.FAN_EXIT), ((fc.VERMILION, 9, 14), fc.VERMILION_TOP), ((rv.ROUTE6, 8, 35), fc.HOUSE_5_EXIT),
                         ((rv.ROUTE5, 16, 28), fc.ROUTE5_TOP), ((fc.CERULEAN, 27, 11), {fc.BIKE_DOOR}), ((cerulean_south.HOUSE, 3, 0), fc.HOUSE_MATS)):
        path = plan(start, goals)
        assert path and plan.follow(start, path)[-1] in goals, start
    south = (fc.CERULEAN, 20, 33)  # Route 5's end: the shop is not reachable on foot from here, the burgled house's hole is
    assert not plan(south, {fc.BIKE_DOOR}) and plan.follow(south, plan(south, {(fc.CERULEAN, 27, 9)}))[-1] == (cerulean_south.HOUSE, 3, 0)
    assert fc.route_step("bike_shop", south, plan)[0] in ("UP", "DOWN", "LEFT", "RIGHT")
