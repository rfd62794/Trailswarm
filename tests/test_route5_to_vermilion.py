"""Stages past to_route5 (to_route6, to_vermilion) had no target: the agent oscillated Cerulean/Route 5 (4000-step live run, 2026-11-15)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent.explorer import cerulean_south, planner_east, route5_vermilion as rv
from pokeagent.goals import GOALS

ROM = Path(__file__).resolve().parents[1] / "roms" / "Pokemon Red.gb"


def _goals(upto):
    return {g: True for g in GOALS[:GOALS.index(upto)]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)


G = SimpleNamespace(path=lambda pos, goal: None, blocked_now=frozenset())


def test_route5_walks_the_planned_route_toward_the_route6_house_door():
    asked = []

    def plan(start, goals, walls=None, blocked=None, hard=None):
        asked.append(goals)
        return ["RIGHT", "DOWN"]
    out = planner_east.east_road_step(G, {}, {**_goals("to_route6"), "_route_plan": plan}, (rv.ROUTE5, 10, 2))
    assert out[0] == "RIGHT" and "Underground Path" in out[1] and asked == [rv.EXIT]


def test_route6_walks_to_the_south_edge_for_vermilion():
    asked = []

    def plan(start, goals, walls=None, blocked=None, hard=None):
        asked.append(goals)
        return ["DOWN"]
    out = planner_east.east_road_step(G, {}, {**_goals("to_vermilion"), "_route_plan": plan}, (rv.ROUTE6, 12, 20))
    assert out[0] == "DOWN" and "Vermilion" in out[1] and asked == [rv.BOTTOM]


def test_door_mat_and_south_edge_press_down():
    assert rv.route_step((rv.PATH_6, 3, 7), lambda *a, **k: ["UP"]) [0] == "DOWN"
    assert rv.route_step((rv.ROUTE6, 14, 35), lambda *a, **k: ["UP"])[0] == "DOWN"
    assert rv.route_step((0x10, 1, 1), None) is None and rv.route_step((0x03, 1, 1), lambda *a, **k: ["UP"]) is None


def test_still_in_cerulean_the_stage_uses_the_cerulean_route():
    plan = lambda start, goals, walls=None, blocked=None, hard=None: ["UP"] if goals == {cerulean_south.HOLE} else None
    out = planner_east.east_road_step(G, {}, {**_goals("to_route6"), "_route_plan": plan}, (cerulean_south.HOUSE, 2, 7))
    assert out[0] == "UP"


@pytest.mark.skipif(not ROM.exists(), reason="needs the ROM")
def test_rom_route_from_route5_reaches_the_house_door_and_route6_edge():
    from pokeagent.atlas.walkgrid import rom_cave_planner
    plan = rom_cave_planner(str(ROM), maps=cerulean_south.MAPS | rv.MAPS)
    path = plan((rv.ROUTE5, 16, 1), rv.EXIT)
    assert path and plan.follow((rv.ROUTE5, 16, 1), path)[-1] in rv.EXIT
    assert {c[0] for c in plan.follow((rv.ROUTE5, 16, 1), path)} >= {rv.PATH_5, rv.PATH_NS, rv.PATH_6}
    assert plan((rv.ROUTE6, 17, 14), rv.BOTTOM)
