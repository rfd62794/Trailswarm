"""The ROM walk grid and the multi-floor cave planner (Mt Moon), including the tile-pair rule and learned-wall pass order."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pokeagent.atlas.walkgrid import bfs, pair_blocked, rom_cave_planner, rom_planner

needs_rom = pytest.mark.skipif(not Path("roms/Pokemon Red.gb").exists(), reason="ROM not present")
EXIT = {(0x3C, 27, 3)}


def test_pair_rule_blocks_an_edge_between_two_walkable_cells():
    tiles = np.array([[0x05, 0x05, 0x20]], dtype=np.uint8)
    grid = np.ones((1, 3), dtype=bool)
    pairs = frozenset({(0x05, 0x20), (0x20, 0x05)})
    assert not pair_blocked(tiles, pairs, (0, 0), (1, 0))   # 05 -> 05 walks
    assert pair_blocked(tiles, pairs, (1, 0), (2, 0))       # 05 -> 20 is blocked
    assert bfs(grid, (0, 0), {(1, 0)}, set(), set(), {}, tiles, pairs) == ["RIGHT"]
    assert bfs(grid, (0, 0), {(2, 0)}, set(), set(), {}, tiles, pairs) is None
    assert bfs(grid, (0, 0), {(2, 0)}, set(), set(), {}) == ["RIGHT", "RIGHT"]  # without the pair table it would walk


@needs_rom
def test_b2f_pocket_reaches_the_exit_across_floors_and_uses_the_5_7_ladder():
    plan = rom_cave_planner()
    start = (0x3D, 15, 24)
    path = plan(start, EXIT)
    assert path
    cells = plan.follow(start, path)
    assert cells[-1] == (0x3C, 27, 3) or cells[-2][0] == 0x3C
    assert (0x3D, 4, 7) in cells and (0x3C, 23, 3) in cells     # the swarm's chain: B2F (5,7) -> B1F (23,3) -> exit
    assert cells.index((0x3D, 4, 7)) < cells.index((0x3C, 23, 3))
    assert len({c[0] for c in cells}) == 3                       # the pocket is cut off on its own floor: 1F is on the way


@needs_rom
def test_b2f_west_region_walks_the_swarms_corridor_to_the_ladder():
    plan = rom_cave_planner()
    start = (0x3D, 9, 29)
    cells = plan.follow(start, plan(start, {(0x3D, 5, 7)}))
    assert (0x3D, 12, 9) in cells and (0x3D, 3, 4) in cells and cells[-1][0] == 0x3C  # via (12,9) and (3,4), up the ladder
    assert (0x3D, 4, 7) in cells


@needs_rom
def test_a_learned_false_wall_cannot_block_a_rom_route_for_good():
    plan = rom_cave_planner()
    start = (0x3C, 23, 3)
    assert plan(start, EXIT) == ["RIGHT"] * 4
    walls = {0x3C: {f"23,3,{d}" for d in ("UP", "DOWN", "LEFT", "RIGHT")}}      # the start tile walled in on every side
    assert plan(start, EXIT, walls=walls) == ["RIGHT"] * 4                      # the bare-ROM pass ignores them
    some = {0x3C: {"23,3,RIGHT", "24,3,RIGHT", "25,3,RIGHT", "26,3,RIGHT"}}
    rerouted = plan(start, EXIT, walls=some)
    assert rerouted and plan.follow(start, rerouted)[-1] == (0x3C, 27, 3)        # a partial set only delays it
    detour = plan(start, EXIT, blocked={0x3C: {(24, 3)}})                       # a temporary NPC block only reroutes
    assert detour and (0x3C, 24, 3) not in plan.follow(start, detour) and plan.follow(start, detour)[-1] == (0x3C, 27, 3)


@needs_rom
def test_single_floor_planner_and_mt_moon_ladder_room():
    plan = rom_planner()
    assert plan(0x3C, (23, 3), [(27, 3)]) == ["RIGHT"] * 4
    assert plan(0x3D, (15, 24), [(5, 7)]) is None   # the 94-cell pocket really is cut off on B2F
