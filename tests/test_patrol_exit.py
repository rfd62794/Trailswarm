"""Cerulean Bike Shop, 2026-11-15: an interior map with no frontier and a learned warp was patrolled for 1,250 steps."""
from types import SimpleNamespace

from pokeagent.explorer import patrol_exit
from pokeagent.explorer.memory import MapMemory
from pokeagent.ramworld import MapHeader


def _ctx(tmp_path, tileset):
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"]["66"] = {"visited": {"4,6": 1, "4,5": 1}, "warps": {"4,6,DOWN": [3, 9, 9]}}
    mem.data["maps"]["3"] = {"visited": {"9,9": 1}}
    return SimpleNamespace(emu=None, mem=mem), tileset


def test_interior_with_a_learned_exit_walks_out(tmp_path, monkeypatch):
    ctx, ts = _ctx(tmp_path, 12)
    monkeypatch.setattr(patrol_exit, "read_map_header", lambda emu: MapHeader(ts, 4, 4, (), (), ()))
    step = patrol_exit.exit_step(ctx, 66, 4, 5)
    assert step and step[0] == "DOWN"
    assert patrol_exit.exit_step(ctx, 66, 4, 6)[0] == "DOWN"


def test_overworld_is_never_force_left(tmp_path, monkeypatch):
    ctx, _ = _ctx(tmp_path, 0)
    monkeypatch.setattr(patrol_exit, "read_map_header", lambda emu: MapHeader(0, 4, 4, (), (), ()))
    assert patrol_exit.exit_step(ctx, 66, 4, 5) is None


def test_unreadable_header_is_no_knowledge(tmp_path, monkeypatch):
    ctx, _ = _ctx(tmp_path, 12)
    def boom(emu):
        raise ValueError("fake")
    monkeypatch.setattr(patrol_exit, "read_map_header", boom)
    assert patrol_exit.exit_step(ctx, 66, 4, 5) is None
