"""Legs and par: synthetic grids and logs (no ROM), plus ROM checks skipped when the ROM is absent."""
from __future__ import annotations

import pytest

from pokeagent.legs import grid as G
from pokeagent.legs.par import par
from pokeagent.legs.split import IDLE_FRAMES, Leg, efficiency, split_legs

W, GR = G.FRAME_WALK, G.GRASS_PENALTY


def test_par_straight_line_and_unreachable():
    g = G.from_ascii(["....", "####", "...."])
    assert par(g, (0, 0), (3, 0))[0] == 3 * W
    assert par(g, (0, 0), (0, 2)) is None
    assert par(g, (1, 0), (1, 0)) == (0.0, [(1, 0)])


def test_par_goes_around_grass_when_cheaper_and_through_when_not():
    g = G.from_ascii(["..g..", "....."])
    # straight along row 0 enters one grass tile (+60); the detour down and back up costs 2 extra steps (32)
    frames, path = par(g, (0, 0), (4, 0))
    assert frames == 6 * W and all(not g.grass[y, x] for x, y in path)
    g2 = G.from_ascii(["..g..", "#####"])  # no way around: pay the grass
    assert par(g2, (0, 0), (4, 0))[0] == 4 * W + GR


def test_par_ledge_is_one_way_and_cheaper_than_the_detour():
    g = G.from_ascii(["..", "v.", "..", "..", ".."])        # ledge at (0,1): hop (0,0) -> (0,2)
    assert par(g, (0, 0), (0, 2))[0] == G.LEDGE_FRAMES      # hop = 2 steps
    assert par(g, (0, 2), (0, 0))[0] == 4 * W               # back UP cannot hop: around via column 1
    assert par(g, (0, 2), (0, 0))[1][1] == (1, 2)


def test_par_warp_tile_is_solid_except_as_goal_and_bike_scales():
    g = G.from_ascii([".W."])
    assert par(g, (0, 0), (2, 0)) is None
    assert par(g, (0, 0), (1, 0))[0] == W
    assert par(g, (0, 0), (1, 0), step=G.FRAME_BIKE)[0] == G.FRAME_BIKE


def _row(step, f, b, t, moved=True):
    return {"step": step, "from": list(f), "button": b, "to": list(t), "moved": moved}


def test_split_legs_across_a_map_change():
    rows = [_row(1, (5, 2, 2), "RIGHT", (5, 3, 2)), _row(2, (5, 3, 2), "A", (5, 3, 2), False),
            _row(3, (5, 3, 2), "DOWN", (7, 4, 4)),                      # leaves map 5 (a warp)
            _row(4, (7, 4, 4), "UP", (7, 4, 3)), _row(5, (7, 4, 3), "UP", (7, 4, 2))]   # still in map 7: incomplete
    a, b = split_legs(rows, "run1")
    assert (a.map, a.entry, a.exit, a.button, a.dest, a.complete) == (5, (2, 2), (3, 2), "DOWN", (7, 4, 4), True)
    assert a.buttons == ["RIGHT", "A", "DOWN"] and a.moved == 2 and a.frames == 2 * W + IDLE_FRAMES
    assert (b.map, b.entry, b.exit, b.complete, b.presses) == (7, (4, 4), (4, 3), False, 2)
    assert a.key == "5:2,2>3,2:DOWN"


def test_split_legs_breaks_on_a_position_jump():
    rows = [_row(1, (1, 0, 0), "RIGHT", (1, 1, 0)), _row(2, (1, 9, 9), "RIGHT", (1, 10, 9))]   # state reload between
    legs = split_legs(rows)
    assert [l.complete for l in legs] == [False, False] and legs[1].entry == (9, 9)


def test_efficiency():
    assert efficiency(100, [200, 400]) == 0.5
    assert efficiency(100, [100]) == 1.0
    assert efficiency(None, [100]) is None and efficiency(100, []) is None
    assert isinstance(Leg("r", 1, (0, 0), (1, 0), "UP", None, 0).key, str)


ROM = G.rom_path()
needs_rom = pytest.mark.skipif(ROM is None, reason="ROM not present")


@needs_rom
def test_rom_ledge_table_matches_hardcoded_constants():
    rom = ROM.read_bytes()
    o, found = 0x1A6CF, set()
    names = {0: "DOWN", 4: "UP", 8: "LEFT", 0xC: "RIGHT"}
    while rom[o] != 0xFF:
        found.add((names[rom[o]], rom[o + 1], rom[o + 2]))
        o += 4
    assert found == G.LEDGES


@needs_rom
def test_route24_south_entry_to_east_edge_par_by_hand():
    # Route 24 (map 35): arrive at (10, 35), corridor x=10 runs straight up to row 9, then row 9 runs east to the edge at x=19:
    # 26 steps up + 9 steps right, no grass (grass is x=4..5 only) = 35 tiles x 16 frames.
    g = G.rom_grids()(35)
    frames, path = par(g, (10, 35), (19, 9))
    assert frames == 35 * W and len(path) == 36


def test_leg_report_drops_legs_with_battle_presses(tmp_path):
    import json
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("leg_report", Path(__file__).resolve().parents[1] / "tools" / "leg_report.py")
    lr = importlib.util.module_from_spec(spec); spec.loader.exec_module(lr)
    rows = [{"step": 1, "from": [5, 0, 0], "button": "RIGHT", "to": [5, 1, 0], "moved": True},
            {"step": 2, "from": [5, 1, 0], "button": "DOWN", "to": [7, 1, 1], "moved": True}]
    run = tmp_path / "explore-x"; run.mkdir()
    (run / "transitions.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (run / "decisions.jsonl").write_text(json.dumps({"step": 2, "battle": True}) + "\n")
    leg = split_legs(rows)[0]
    assert leg.step1 == 2 and lr.fought(lr.fight_steps(run / "decisions.jsonl"), leg)
    assert not lr.fought(set(), leg)
