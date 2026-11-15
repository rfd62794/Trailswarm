"""A run that starts inside a house knows no warp: standing on a header door tile with nothing left to explore it presses out once."""
from types import SimpleNamespace

from pokeagent.explorer.door_exit import door_press
from pokeagent.explorer.memory import MapMemory
from pokeagent.ramworld import MapHeader, Warp
from pokeagent.explorer import door_exit


def _ctx(tmp_path):
    return SimpleNamespace(emu=None, mem=MapMemory(tmp_path / "maps.json"))


def test_edge_door_tile_presses_out_once(tmp_path, monkeypatch):
    monkeypatch.setattr(door_exit, "read_map_header", lambda emu: MapHeader(0, 4, 4, (Warp(7, 2, 0, 255), Warp(7, 3, 0, 255)), (), ()))
    ctx = _ctx(tmp_path)
    assert door_press(ctx, 88, 1, 7) is None                       # not a door tile
    assert door_press(ctx, 88, 2, 5) is None                       # not an edge
    got = door_press(ctx, 88, 2, 7)
    assert got and got[0] == "DOWN"
    assert door_press(ctx, 88, 2, 7)                               # the first exit may bounce back in: one more try
    assert door_press(ctx, 88, 2, 7) is None                       # tried twice: no loop
    ctx.mem.m(88)["fails"] = {"3,7,DOWN": 1}
    assert door_press(ctx, 88, 3, 7) is None                       # a real press already failed there


def test_unreadable_header_is_no_knowledge(tmp_path, monkeypatch):
    def boom(emu):
        raise ValueError("fake")
    monkeypatch.setattr(door_exit, "read_map_header", boom)
    assert door_press(_ctx(tmp_path), 88, 2, 7) is None
