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


@needs_rom
def test_a_person_just_bumped_stays_blocked_even_when_it_is_the_only_way(tmp_path):
    """Mt Moon B2F (12,9): 31 UP presses into a trainer on the straight line; the temp block must survive the object-free pass."""
    plan = rom_cave_planner()
    start = (0x3D, 12, 9)
    straight = plan(start, {(0x3D, 12, 3)})
    assert straight and straight[0] == "UP"
    detour = plan(start, {(0x3D, 12, 3)}, blocked={0x3D: {(12, 8)}})
    assert detour is None or detour[0] != "UP"          # never the bumped tile again while the block lasts


class StubPlan:
    """A one-corridor 'planner': RIGHT x4 along B1F y=3, counting calls and the hard walls it was given."""
    def __init__(self):
        self.calls, self.hard_seen = 0, []

    def __call__(self, start, goals, walls=None, blocked=None, hard=None):
        self.calls += 1
        self.hard_seen.append({m: set(v) for m, v in (hard or {}).items()})
        return ["RIGHT"] * (27 - start[1]) if start[0] == 0x3C else None

    def follow(self, start, buttons):
        return [(start[0], start[1] + i, start[2]) for i in range(len(buttons) + 1)]

    def warp_tiles(self, m, d=None):
        return set()


def test_route_is_planned_once_and_replanned_only_when_we_leave_it_or_the_block_set_changes():
    from pokeagent.explorer.cave_route import rom_route_step
    plan, cache = StubPlan(), {}
    for x in (23, 24, 25, 26):
        assert rom_route_step({}, "through_mt_moon", (0x3C, x, 3), plan, (), cache)[0] == "RIGHT"
    assert plan.calls == 1                                              # one BFS for four presses
    rom_route_step({}, "through_mt_moon", (0x3C, 25, 4), plan, (), cache)   # knocked off the path: re-plan
    assert plan.calls == 2
    rom_route_step({}, "through_mt_moon", (0x3C, 25, 4), plan, ((0x3C, 26, 4),), cache)  # an NPC block appeared
    assert plan.calls == 3


def test_an_edge_that_fails_repeatedly_becomes_a_hard_wall_for_the_run():
    from pokeagent.explorer.cave_route import MAX_BUMPS, rom_route_step
    plan, cache = StubPlan(), {}
    pos = (0x3C, 23, 3)
    for _ in range(MAX_BUMPS + 1):                                       # asked again from the same tile: the press went nowhere
        rom_route_step({}, "through_mt_moon", pos, plan, (), cache)
    assert (0x3C, "23,3,RIGHT") in cache["edges"]
    assert any("23,3,RIGHT" in h.get(0x3C, ()) for h in plan.hard_seen[1:])  # and the planner is told on every later pass
    cache2 = {}
    for x in range(23, 27):                                              # moving along resets the count: never a wall
        rom_route_step({}, "through_mt_moon", (0x3C, x, 3), plan, (), cache2)
    assert not cache2["edges"]


@needs_rom
def test_walk_cells_never_raises_for_any_parsable_header():
    """Unused ids (11, 204-206, 237-238, 241-244, ...) used to raise IndexError in walk_cells (same on main): empty grid instead."""
    from pokeagent.atlas import rom_maps
    from pokeagent.atlas.fit import walk_cells
    rom = rom_maps.load()
    n = 0
    for i in range(256):
        try:
            hd = rom_maps.header(rom, i)
        except IndexError:
            continue  # the header itself does not parse (callers use all_headers, which filters these)
        grid = walk_cells(rom, hd)
        assert grid.ndim == 2 and grid.dtype == bool
        n += 1
    assert n > 200


def test_hard_walls_expire_clear_on_a_floor_change_and_never_go_under_an_npc():
    from pokeagent.explorer.cave_route import HARD_WALL_ASKS, MAX_BUMPS, rom_route_step
    plan, cache = StubPlan(), {}
    pos = (0x3C, 23, 3)
    for _ in range(MAX_BUMPS + 1):
        rom_route_step({}, "through_mt_moon", pos, plan, (), cache)
    assert cache["edges"]
    for x in range(HARD_WALL_ASKS + 2):                                    # time passes (asks elsewhere on the floor)
        rom_route_step({}, "through_mt_moon", (0x3C, 10 + x % 5, 3), plan, (), cache)
    assert not cache["edges"]                                              # expired
    for _ in range(MAX_BUMPS + 1):
        rom_route_step({}, "through_mt_moon", pos, plan, (), cache)
    assert cache["edges"]
    rom_route_step({}, "through_mt_moon", (0x3D, 9, 9), plan, (), cache)    # a floor change drops them
    assert not cache["edges"]
    npc, cache3 = StubPlan(), {}
    for _ in range(MAX_BUMPS + 1):                                         # (24,3) holds a wanderer: wait for it, no wall
        rom_route_step({}, "through_mt_moon", pos, npc, ((0x3C, 24, 3),), cache3)
    assert not cache3["edges"]


@needs_rom
def test_a_hard_wall_on_the_only_path_makes_the_planner_fall_back_and_the_route_returns_after_expiry():
    from pokeagent.explorer.cave_route import HARD_WALL_ASKS, rom_route_step
    plan = rom_cave_planner()
    cut = {0x3C: {"26,3,RIGHT", "27,2,DOWN", "27,4,UP"}}                   # every way onto the exit tile (27,3)
    pos = (0x3C, 26, 3)
    assert plan(pos, EXIT) == ["RIGHT"] and plan(pos, EXIT, hard=cut) is None
    cache = {"tick": 0, "floor": 0x3C, "edges": {(0x3C, e): HARD_WALL_ASKS for e in cut[0x3C]}}   # three bumps' worth of walls
    assert rom_route_step({}, "through_mt_moon", pos, plan, (), cache) is None      # walled in: today's logic takes over
    for _ in range(HARD_WALL_ASKS):                                                  # time passes
        rom_route_step({}, "through_mt_moon", (0x3C, 20, 3), plan, (), cache)
    assert not cache["edges"]
    assert rom_route_step({}, "through_mt_moon", pos, plan, (), cache)[0] == "RIGHT"  # expired: the ROM route is back



def test_a_person_on_the_only_next_tile_makes_the_route_wait_instead_of_bumping():
    from pokeagent.explorer.cave_route import rom_route_step
    plan, cache = StubPlan(), {}
    pos = (0x3C, 23, 3)
    assert rom_route_step({}, "through_mt_moon", pos, plan, (), cache)[0] == "RIGHT"
    button, why = rom_route_step({}, "through_mt_moon", pos, plan, ((0x3C, 24, 3),), cache)   # the NPC stands at (24,3)
    assert button == "" and "waiting" in why                    # a no-press step: the person gets time to walk away
    assert rom_route_step({}, "through_mt_moon", pos, plan, (), cache)[0] == "RIGHT"          # block decayed: go


def test_a_person_who_never_moves_is_walled_after_a_few_wait_cycles_and_the_route_goes_around():
    from pokeagent.explorer.cave_route import WAIT_CYCLES, rom_route_step
    plan, cache = StubPlan(), {}
    pos, npc = (0x3C, 23, 3), ((0x3C, 24, 3),)
    answers = []
    for _ in range(WAIT_CYCLES + 1):
        answers.append(rom_route_step({}, "through_mt_moon", pos, plan, npc, cache))     # blocked: wait
        answers.append(rom_route_step({}, "through_mt_moon", pos, plan, npc, cache))     # still blocked: same episode
        rom_route_step({}, "through_mt_moon", pos, plan, (), cache)                       # the block decayed: a real press
    waits = [a for a in answers if a and a[0] == ""]
    assert len(waits) >= WAIT_CYCLES                       # it did wait the first cycles ...
    assert (0x3C, "23,3,RIGHT") in cache["edges"]          # ... then hard-walled the edge for its window
    assert answers[-2][0] == "RIGHT" and "around" in answers[-2][1]   # and asked the planner for another way
    assert any("23,3,RIGHT" in h.get(0x3C, ()) for h in plan.hard_seen[-2:])
