"""After Bill's S.S. Ticket the next stage (to_route5) had no target, so the agent patrolled Bill's house (live marathon, 2026-11-15)."""
from types import SimpleNamespace

from pokeagent.explorer import planner_east
from pokeagent.goals import GOALS


def _goals():
    return {g: True for g in GOALS[:GOALS.index("to_route5")]}


def test_from_bills_house_the_planner_walks_back_toward_cerulean(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)
    seen = []
    g = SimpleNamespace(path=lambda pos, goal: seen.append(goal) or (["DOWN"] if goal((planner_east.CERULEAN, 0, 0)) else None), blocked_now=frozenset())
    out = planner_east.east_road_step(g, {}, _goals(), (0x58, 2, 6))
    assert out and out[0] == "DOWN" and "Cerulean" in out[1]


def test_in_cerulean_the_rom_route_leads_through_the_burgled_house(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)
    g = SimpleNamespace(path=lambda pos, goal: None, blocked_now=frozenset())
    out = planner_east.east_road_step(g, {}, _goals(), (planner_east.CERULEAN, 27, 13))
    assert out and out[0] in ("UP", "LEFT", "RIGHT") and "hole" in out[1]  # the wall at row 28 has no Cut-free gap: round by the house


def test_rom_route_in_the_house_and_back_yard():
    from pokeagent.explorer import cerulean_south as cs
    assert cs.route_step((cs.HOUSE, 2, 7))[0] == "UP"                  # inside, heading for the hole at (3, 0)
    assert "Route 5" in cs.route_step((cs.CERULEAN, 27, 8))[1]          # behind the house: the south region is open
    assert cs.route_step((cs.CERULEAN, 20, 35)) == ("DOWN", "goal to_route5: on Cerulean's south edge, pushing DOWN onto Route 5")
    assert cs.route_step((0x10, 1, 1)) is None


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
