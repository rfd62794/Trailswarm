"""Cerulean Bike Shop, 2026-11-15: an interior map with no frontier and a learned warp was patrolled for 1,250 steps."""
from types import SimpleNamespace

import pytest

from pokeagent.explorer import patrol_exit
from pokeagent.explorer.memory import MapMemory
from pokeagent.ramworld import MapHeader


@pytest.fixture
def ctx(tmp_path, monkeypatch, request):
    mem = MapMemory(tmp_path / "maps.json")
    for m in (0x42, 0x3C, 0x40, 0x5F):  # an interior, a Mt Moon floor, a Pokecenter, a ship deck
        mem.data["maps"][str(m)] = {"visited": {"4,6": 1, "4,5": 1}, "warps": {"4,6,DOWN": [3, 9, 9]}}
    mem.data["maps"]["3"] = {"visited": {"9,9": 1}}
    monkeypatch.setattr(patrol_exit, "read_map_header", lambda emu: MapHeader(12, 4, 4, (), (), ()))
    return SimpleNamespace(emu=None, mem=mem, stage_goal="to_route5", center_intent=None, step=100)


def test_interior_with_a_learned_exit_walks_out(ctx):
    assert patrol_exit.exit_step(ctx, 0x42, 4, 5)[0] == "DOWN"
    assert patrol_exit.exit_step(ctx, 0x42, 4, 6)[0] == "DOWN"


def test_overworld_is_never_force_left(ctx, monkeypatch):
    monkeypatch.setattr(patrol_exit, "read_map_header", lambda emu: MapHeader(0, 4, 4, (), (), ()))
    assert patrol_exit.exit_step(ctx, 0x42, 4, 5) is None


def test_unreadable_header_is_no_knowledge(ctx, monkeypatch):
    def boom(emu):
        raise ValueError("fake")
    monkeypatch.setattr(patrol_exit, "read_map_header", boom)
    assert patrol_exit.exit_step(ctx, 0x42, 4, 5) is None


@pytest.mark.parametrize("m", [0x3C, 0x40, 0x5F])  # cave, Pokecenter, ship
def test_caves_centers_and_ships_are_skipped(ctx, m):
    assert patrol_exit.exit_step(ctx, m, 4, 5) is None


def test_center_intent_and_a_target_on_this_map_are_skipped(ctx):
    ctx.center_intent = "heal"
    assert patrol_exit.exit_step(ctx, 0x42, 4, 5) is None
    ctx.center_intent, ctx.stage_goal = None, "buy_magikarp"          # target 0x44: elsewhere, fires
    assert patrol_exit.exit_step(ctx, 0x42, 4, 5)
    assert patrol_exit.exit_step(ctx, 0x44, 4, 5) is None              # standing ON the target map
    ctx.stage_goal = "no_such_stage"                                    # no map target: nothing to leave for
    assert patrol_exit.exit_step(ctx, 0x42, 4, 5) is None


def test_ping_pong_guard_stops_after_three_exits_in_the_window(ctx):
    for i in range(patrol_exit.EXIT_CAP):
        ctx.step = 100 + i * 50
        assert patrol_exit.exit_step(ctx, 0x42, 4, 6)                  # the exit press itself (1 step)
    ctx.step = 300
    assert patrol_exit.exit_step(ctx, 0x42, 4, 6) is None
    ctx.step = 100 + patrol_exit.EXIT_WINDOW + 200                      # the window passed
    assert patrol_exit.exit_step(ctx, 0x42, 4, 6)
