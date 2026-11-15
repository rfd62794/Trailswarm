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


def test_in_cerulean_exploration_finds_the_south_exit(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)
    g = SimpleNamespace(path=lambda pos, goal: None, blocked_now=frozenset())
    assert planner_east.east_road_step(g, {}, _goals(), (planner_east.CERULEAN, 5, 5)) is None
