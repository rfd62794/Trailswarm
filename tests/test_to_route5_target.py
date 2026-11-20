"""After Bill's S.S. Ticket the next stage (to_route5) had no target, so the agent patrolled Bill's house (live marathon, 2026-11-15)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent.explorer import cerulean_south, planner_east
from pokeagent.goals import GOALS

ROM = Path(__file__).resolve().parents[1] / "roms" / "Pokemon Red.gb"


def _goals():
    return {g: True for g in GOALS[:GOALS.index("to_route5")]}


def test_from_bills_house_the_planner_walks_back_toward_cerulean(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)
    seen = []
    g = SimpleNamespace(path=lambda pos, goal: seen.append(goal) or (["DOWN"] if goal((planner_east.CERULEAN, 0, 0)) else None), blocked_now=frozenset())
    out = planner_east.east_road_step(g, {}, _goals(), (0x58, 2, 6))
    assert out and out[0] == "DOWN" and "Cerulean" in out[1]


def test_in_cerulean_the_injected_rom_route_leads_through_the_burgled_house(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)
    g = SimpleNamespace(path=lambda pos, goal: None, blocked_now=frozenset())
    asked = []

    def plan(start, goals, walls=None, blocked=None, hard=None):
        asked.append(goals)
        return None if goals is cerulean_south.BOTTOM else ["UP", "UP"]  # the south region is cut off from the town side

    out = planner_east.east_road_step(g, {}, {**_goals(), "_route_plan": plan}, (planner_east.CERULEAN, 27, 13))
    assert out == ("UP", "goal to_route5: 2 steps toward the burgled house's hole (the way round the wall, no Cut)")
    assert planner_east.east_road_step(g, {}, _goals(), (planner_east.CERULEAN, 27, 13)) is None  # no ROM planner: exploration
    assert planner_east.east_road_step(g, {}, {**_goals(), "_route_plan": plan}, (cerulean_south.HOUSE, 2, 7))[0] == "UP"  # never walked out of the house


def test_route_step_edge_and_back_yard_with_a_fake_planner():
    plan = lambda start, goals, walls=None, blocked=None, hard=None: ["DOWN"] if goals is cerulean_south.BOTTOM else None
    assert "Route 5" in cerulean_south.route_step((cerulean_south.CERULEAN, 27, 8), plan)[1]
    assert cerulean_south.route_step((cerulean_south.CERULEAN, 27, 35), plan) == ("DOWN", "goal to_route5: on Cerulean's south edge, pushing DOWN onto Route 5")
    assert cerulean_south.route_step((0x10, 1, 1), plan) is None


@pytest.mark.skipif(not ROM.exists(), reason="needs the Pokemon Red ROM")
def test_real_rom_route_goes_round_by_the_burgled_house():
    from pokeagent.atlas.walkgrid import rom_cave_planner
    plan = rom_cave_planner(str(ROM), maps=cerulean_south.MAPS)
    assert cerulean_south.route_step((cerulean_south.HOUSE, 2, 7), plan)[0] == "UP"
    assert plan((cerulean_south.CERULEAN, 27, 13), cerulean_south.BOTTOM) is None  # town side: walled off, so the house first
    assert "Route 5" in cerulean_south.route_step((cerulean_south.CERULEAN, 27, 8), plan)[1]


def _done_through_ticket():
    return {g: True for g in GOALS[:GOALS.index("to_route5")]}


def test_plan_step_dispatches_to_route5_after_the_ticket():
    """ss_ticket done, to_vermilion not: plan_step returned None (east_road_step was gated on to_vermilion), so to_route5 never ran."""
    from pokeagent.explorer.planner import plan_step
    assert _done_through_ticket()["ss_ticket"]
    maps = {"3": {"visited": {"5,5": 1, "5,6": 1}}, "0": {}}
    maps["88"] = {"visited": {"2,2": 1}, "warps": {"2,2,DOWN": [3, 5, 5]}}
    step = plan_step(_done_through_ticket(), maps, (0x58, 2, 2), "UP")
    assert step and step[0] == "DOWN" and "Cerulean" in step[1]


def test_in_cerulean_pushes_to_the_southern_edge():
    maps = {str(planner_east.CERULEAN): {"visited": {"5,5": 1, "5,6": 1, "6,5": 1}}}
    g = SimpleNamespace(path=lambda pos, goal: None, blocked_now=frozenset())
    out = planner_east._edge_frontier(g, maps, (planner_east.CERULEAN, 5, 6), "to_route5", "DOWN")
    assert out == ("DOWN", "goal to_route5: at the southernmost open tile, pushing DOWN for the map edge")
