"""Mt Moon sinks (2026-11-05): a walking NPC read as 'busy' (A pressed 164x), Magikarp swap-training inside the cave,
wild fights vs owned species inside the cave, and wandering instead of heading for the ROM header's ladder."""
from __future__ import annotations

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import battle_run as br
from pokeagent.explorer.behaviours import cave_escape  # noqa: F401  (import check)
from pokeagent.explorer.behaviours.party_order import trainee_home
from pokeagent.explorer.behaviours.readiness import Readiness, walker_near
from pokeagent.atlas.ladders import rom_ladders
from pokeagent.explorer import cave_route
from pokeagent.explorer.world import WorldGraph
from test_battle_types import make_ctx


def _npc(ctx, slot, x, y, move=2):
    ctx.emu.set(0xC100 + 16 * slot, 6); ctx.emu.set(0xC101 + 16 * slot, move)
    ctx.emu.set(0xC205 + 16 * slot, x + 4); ctx.emu.set(0xC204 + 16 * slot, y + 4); ctx.emu.set(0xC206 + 16 * slot, 0xFF)


def test_walker_near_only_for_random_walkers_within_radius(tmp_path):
    ctx = make_ctx(tmp_path, {0xD35E: 0x3B})  # player at (5,6) on Mt Moon 1F
    ctx.refresh()
    assert not walker_near(ctx)
    _npc(ctx, 1, 6, 6, move=1)         # standing NPC: not a walker
    assert not walker_near(ctx)
    _npc(ctx, 2, 9, 6)                 # walker 4 tiles away: outside the radius
    assert not walker_near(ctx)
    _npc(ctx, 3, 7, 7)
    assert walker_near(ctx)


def test_a_walker_nearby_is_not_busy_but_a_still_changing_empty_screen_is(tmp_path):
    ctx = make_ctx(tmp_path, {0xD35E: 0x3B})
    ctx.refresh(); ctx.stable_frames = 0
    assert Readiness()._busy(ctx)      # cutscene-like: screen moving, nobody walking
    _npc(ctx, 3, 6, 6)
    assert not Readiness()._busy(ctx)  # the NPC explains the motion: no "A in case text is waiting"
    ctx.emu.set(0xCD6B, 1)
    assert Readiness()._busy(ctx)      # but a joypad-ignored game is busy whatever walks


def test_magikarp_trainee_belongs_last_inside_the_cave_first_outside(tmp_path):
    ctx = make_ctx(tmp_path, {0xD163: 3, 0xD35E: 0x3B}); ctx.refresh()
    assert trainee_home(ctx) == 2
    ctx.emu.set(0xD35E, 0x0E); ctx.refresh()
    assert trainee_home(ctx) == 0


def test_cave_run_for_wild_cave_fights_except_catch_targets_and_after_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "ROM_KB", {"dex_of_internal": {"107": 41, "34": 1}})
    ctx = make_ctx(tmp_path, {0xD35E: 0x3B, 0xD2F7 + 5: 0b00000001}); ctx.refresh()  # dex 41 owned
    assert br.cave_run(ctx, 1, 107)           # ZUBAT, owned
    assert br.cave_run(ctx, 1, 34)            # not owned but no ball in the bag: nothing to catch it with, so run too
    assert not br.cave_run(ctx, 1, 34, balls=3)  # a catch target (ball + unowned dex entry) is fought/caught
    assert br.cave_run(ctx, 1, 107, balls=3)  # owned: never a target
    ctx.cave_runs = br.MAX_CAVE_RUNS
    assert not br.cave_run(ctx, 1, 107)       # a failed-escape loop gives up and fights
    ctx.cave_runs = 0
    assert not br.cave_run(ctx, 2, 107)       # trainer battle: cannot run
    assert not br.cave_run(ctx, 1, 0)
    ctx.emu.set(0xD35E, 0x0E); ctx.refresh()
    assert not br.cave_run(ctx, 1, 107)       # outside a dungeon the old rules apply


def _graph():
    visited = {f"{x},5": 1 for x in range(1, 9)}   # a corridor along y=5, x 1..8
    return {"59": {"visited": visited, "warps": {}, "blocked": []}}


def test_ladder_step_walks_to_the_known_tile_nearest_the_ladder():
    ladders = lambda m, d, near=None: [(20, 5)]  # noqa: E731
    maps = {str(0x3B): _graph()["59"]}
    r = cave_route.ladder_step(WorldGraph(maps), maps, "mt_moon_b1f", (0x3B, 2, 5), ladders)
    assert r and r[0] == "RIGHT" and "ROM ladder" in r[1]
    assert cave_route.ladder_step(WorldGraph(maps), maps, "mt_moon_b1f", (0x3B, 8, 5), ladders) is None  # at the closest
    maps[str(0x3B)]["visited"]["8,5"] = cave_route.MAX_PULL_VISITS                 # tried enough: no more pull
    assert cave_route.ladder_step(WorldGraph(maps), maps, "mt_moon_b1f", (0x3B, 2, 5), ladders) is not None  # (7,5) still pulls
    assert cave_route.ladder_step(WorldGraph(maps), maps, "to_route3", (0x3B, 2, 5), ladders) is None
    assert cave_route.ladder_step(WorldGraph(maps), maps, "mt_moon_b1f", (0x3B, 2, 5), None) is None


def test_rom_header_ladders_for_mt_moon():
    from pathlib import Path
    if not Path("roms/Pokemon Red.gb").exists():
        pytest.skip("ROM not present")
    ladders = rom_ladders()
    assert (5, 5) in ladders(0x3B, 0x3C)
    assert ladders(0x3C, 0x0F) == [(27, 3)]


# --- the walker / NPC-in-the-way rules are dungeon-only ---
from pokeagent.explorer.press_frame import PressFrame  # noqa: E402
from pokeagent.explorer.press_interact import record_interaction  # noqa: E402


def test_walker_rule_is_off_outside_dungeons(tmp_path):
    """A scripted walker (rival, Oak) on a town map must still get the busy-A nudge."""
    ctx = make_ctx(tmp_path, {0xD35E: 0x00})  # Pallet Town
    ctx.refresh(); ctx.stable_frames = 0
    _npc(ctx, 3, 6, 6)
    assert not walker_near(ctx) and Readiness()._busy(ctx)
    ctx.emu.set(0xD35E, 0x3B); ctx.refresh()
    assert walker_near(ctx) and not Readiness()._busy(ctx)


@pytest.mark.parametrize("map_id,blocked", [(0x3B, True), (0x00, False), (0x44, False)])
def test_person_in_the_way_temp_blocks_only_in_dungeons(tmp_path, map_id, blocked):
    """A person ahead blocks routing for a while inside the cave; in a town/Pokecenter they may be the target (Mom, nurse)."""
    ctx = make_ctx(tmp_path, {0xD35E: map_id})
    _npc(ctx, 1, 6, 6, move=1)  # an NPC at (6,6): the tile east of the player at (5,6)
    ctx.refresh()
    record_interaction(ctx, PressFrame("RIGHT", "agent", "t", before=(map_id, 5, 6), after=(map_id, 5, 6)))
    assert ((map_id, 6, 6) in ctx.mem.temp_blocked) is blocked
    assert not any("6,6,RIGHT" in k or k.startswith("5,6,RIGHT") for k in ctx.mem.m(map_id)["blocked"])  # never a wall


def test_loop_guard_backs_out_of_an_unrecognised_page_with_b(tmp_path):
    """Mt Moon B2F: START (stall escalation) -> menu A opened a Pokedex page; every direction press then failed."""
    from pokeagent.explorer.behaviours.guards import DIR_FAIL_BACKOUT, LoopGuard
    ctx = make_ctx(tmp_path)
    decisions = []
    for _ in range(DIR_FAIL_BACKOUT + 1):
        ctx.refresh(); ctx.last_press = "UP"
        decisions.append(LoopGuard().step(ctx))
    assert [d.rule for d in decisions if d] == ["unknown_screen_back_out"] and ctx.shake == 0
    ctx.emu.set(0xD362, 6); ctx.refresh()  # the player moved: the counter restarts
    ctx.last_press = "UP"
    assert LoopGuard().step(ctx) is None and ctx.dir_fail == 0


def test_b2f_exit_ladder_is_the_one_landing_beside_the_b1f_exit():
    """The swarm's through_mt_moon run left B2F by (5,7) -> B1F (23,3) -> (27,3) -> Route 4; the other B2F ladders land elsewhere."""
    from pathlib import Path
    if not Path("roms/Pokemon Red.gb").exists():
        pytest.skip("ROM not present")
    ladders = rom_ladders()
    assert ladders(0x3D, 0x3C, (27, 3)) == [(5, 7)]
    assert (5, 7) in ladders(0x3D, 0x3C) and len(ladders(0x3D, 0x3C)) == 4
    called = []
    maps = {str(0x3D): {"visited": {f"{x},5": 1 for x in range(5, 12)}, "warps": {}, "blocked": []}}
    spy = lambda m, d, near=None: called.append(near) or ladders(m, d, near)  # noqa: E731
    r = cave_route.ladder_step(WorldGraph(maps), maps, "through_mt_moon", (0x3D, 11, 5), spy)
    assert called == [(27, 3)] and r and r[0] == "LEFT"  # known tile nearest (5,7) is (5,5): walk west


def test_learned_solid_never_overrides_the_rom_collision_list(tmp_path):
    """Cavern ids 05/15/18/1A/20/21/22/2A/2D/30 are walkable in the ROM; maps.json had 05,05,... keys with 'solid' 15."""
    from pokeagent.explorer.memory import MapMemory
    mem = MapMemory(tmp_path / "m.json")
    ahead_walkable_bl, ahead_wall = [0x29, 0x29, 0x05, 0x05], [0x31, 0x05, 0x31, 0x05]
    for _ in range(5):
        mem.learn_tiles(17, ahead_walkable_bl, walkable=False); mem.learn_tiles(17, ahead_wall, walkable=False)
    assert mem.known_solid(17, ahead_walkable_bl)  # no ROM data wired: old behaviour
    mem.rom_walkable = lambda ts: frozenset({0x05, 0x15, 0x18, 0x1A, 0x20, 0x21, 0x22, 0x2A, 0x2D, 0x30}) if ts == 17 else frozenset()
    assert not mem.known_solid(17, ahead_walkable_bl)          # stepping tile 05 is ROM-walkable: never solid
    assert mem.known_solid(17, ahead_wall)                      # 31 is not in the list: learned solid stands
    before = dict(mem.data["tile_types"]["17"])
    mem.learn_tiles(17, [0x29, 0x29, 0x20, 0x20], walkable=False)
    assert mem.data["tile_types"]["17"] == before              # not even recorded


def test_rom_collision_list_for_the_cavern_tileset():
    from pathlib import Path
    from pokeagent.atlas.collision import rom_walkable_ids
    if not Path("roms/Pokemon Red.gb").exists():
        pytest.skip("ROM not present")
    ids = rom_walkable_ids()(17)
    assert {0x05, 0x20, 0x21, 0x15} <= ids and 0x31 not in ids


def test_rom_tile_pairs_for_the_cavern_and_ship_tilesets():
    from pathlib import Path
    from pokeagent.atlas.collision import rom_tile_pairs
    if not Path("roms/Pokemon Red.gb").exists():
        pytest.skip("ROM not present")
    pairs = rom_tile_pairs()
    assert {(0x20, 0x05), (0x05, 0x20), (0x41, 0x05), (0x2A, 0x05), (0x05, 0x21)} <= pairs(17)
    assert (0x05, 0x05) not in pairs(17) and (0x30, 0x2E) in pairs(3) and pairs(1) == frozenset()


def test_pair_blocked_edges_are_solid_from_the_stand_tile_but_the_same_tile_is_walkable_from_elsewhere(tmp_path):
    from pokeagent.explorer.memory import MapMemory
    mem = MapMemory(tmp_path / "m.json")
    mem.rom_walkable = lambda ts: frozenset({0x05, 0x20, 0x21, 0x2A, 0x41}) if ts == 17 else frozenset()
    mem.rom_pairs = lambda ts: frozenset({(0x20, 0x05), (0x05, 0x20), (0x05, 0x21), (0x21, 0x05)}) if ts == 17 else frozenset()
    ahead20 = [0x20, 0x20, 0x20, 0x20]
    assert mem.known_solid(17, ahead20, stand=0x05)         # 05 -> 20: blocked by the pair table, both walkable
    assert not mem.known_solid(17, ahead20, stand=0x20)     # 20 -> 20 walks
    assert not mem.known_solid(17, [0x05] * 4, stand=0x05)  # 05 -> 05 walks
    assert mem.known_solid(17, [0x05] * 4, stand=0x20)      # 20 -> 05 is the same pair, other direction
    assert not mem.known_solid(17, ahead20)                 # no stand tile known: the walkable-wins rule
    mem.learn_tiles(17, ahead20, walkable=False, stand=0x05)
    assert not mem.data.get("tile_types", {}).get("17")     # a pair failure is not recorded against the ahead tile


def test_stand_tile_is_the_bottom_left_of_the_players_cell():
    from pokeagent.explorer.perceive import stand_tile
    tm = bytearray(360); tm[9 * 20 + 8] = 0x05; tm[8 * 20 + 8] = 0x99
    assert stand_tile(bytes(tm)) == 0x05
