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


def test_cave_run_only_for_owned_species_in_wild_cave_fights(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "ROM_KB", {"dex_of_internal": {"107": 41, "34": 1}})
    ctx = make_ctx(tmp_path, {0xD35E: 0x3B, 0xD2F7 + 5: 0b00000001}); ctx.refresh()  # dex 41 owned
    assert br.cave_run(ctx, 1, 107)           # ZUBAT, owned
    assert not br.cave_run(ctx, 1, 34)        # dex 1 not owned: a new species is still worth it
    assert not br.cave_run(ctx, 2, 107)       # trainer battle: cannot run
    assert not br.cave_run(ctx, 1, 0)
    ctx.emu.set(0xD35E, 0x0E); ctx.refresh()
    assert not br.cave_run(ctx, 1, 107)       # outside a dungeon the old rules apply


def _graph():
    visited = {f"{x},5": 1 for x in range(1, 9)}   # a corridor along y=5, x 1..8
    return {"59": {"visited": visited, "warps": {}, "blocked": []}}


def test_ladder_step_walks_to_the_known_tile_nearest_the_ladder():
    ladders = lambda m, d: [(20, 5)]  # noqa: E731
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
