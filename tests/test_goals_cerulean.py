"""Goals from Mt Moon to the S.S. Ticket: detectors (ROM-verified ids) and the planner's east-road steps."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS, check_goals

MAP, PX, PY, BADGES = 0xD35E, 0xD362, 0xD361, 0xD356
BEFORE = {g: True for g in GOALS[:GOALS.index("to_cerulean") + 1]}


def test_mt_moon_floors_and_crossing_use_seen_maps_and_position():
    emu, st = FakeEmulator({MAP: 0x3C, BADGES: 1}), {}
    g = check_goals(emu, st)
    assert g["mt_moon_b1f"] and not g["mt_moon_b2f"] and not g["through_mt_moon"]
    emu.set(MAP, 0x3D)
    assert check_goals(emu, st)["mt_moon_b2f"]
    emu.set(MAP, 0x0F); emu.set(PX, 18)  # back out of the WEST entrance: not through
    assert not check_goals(emu, st)["through_mt_moon"]
    emu.set(PX, 24)  # the exit warp's landing tile
    assert check_goals(emu, st)["through_mt_moon"]
    emu.set(MAP, 0x0E); emu.set(PX, 3)
    assert check_goals(emu, st)["through_mt_moon"]  # sticky


def test_route4_east_without_b2f_is_not_through():
    emu = FakeEmulator({MAP: 0x0F, PX: 30})
    assert not check_goals(emu, {})["through_mt_moon"]


def test_cerulean_goal_detectors():
    emu, st = FakeEmulator({MAP: 0x40, 0xD163: 1, 0xD16D: 30, 0xD18E: 30}), {}  # one Pokemon, 30/30
    g = check_goals(emu, st)
    assert g["heal_cerulean"] and g["through_mt_moon"] is False and not g["beat_misty"]
    emu.set(BADGES, 1); assert not check_goals(emu, st)["beat_misty"]  # Boulder is not Cascade
    emu.set(BADGES, 3); assert check_goals(emu, st)["beat_misty"]
    emu.set(MAP, 0x23); assert check_goals(emu, st)["nugget_bridge"]
    emu.set(MAP, 0x58); assert check_goals(emu, st)["to_bill"]
    assert not check_goals(emu, st)["ss_ticket"]
    emu.set(0xD31D, 1); emu.set(0xD31E, 0x3F); emu.set(0xD31F, 1)
    assert check_goals(emu, st)["ss_ticket"]


def _mem(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    for m, tiles in ((0x03, [(5, 5), (6, 5)]), (0x41, [(4, 13)]), (0x23, [(3, 9), (3, 8)]), (0x0F, [(30, 5), (31, 5)])):
        for x, y in tiles:
            mem.m(m)["visited"][f"{x},{y}"] = 1
    mem.m(0x03)["warps"]["6,5,DOWN"] = [0x41, 4, 13]
    mem.m(0x03)["warps"]["5,5,UP"] = [0x23, 3, 9]
    mem.m(0x41)["warps"]["4,13,DOWN"] = [0x03, 6, 5]
    return mem.data["maps"]


def test_misty_goes_to_the_gym_when_strong_and_to_route24_when_weak(tmp_path):
    maps = _mem(tmp_path)
    goals = {**BEFORE, "heal_cerulean": True, "_hp": (40, 40), "_level": 20, "_train_level": 8}
    step = plan_step(goals, maps, (0x03, 5, 5), "UP")
    assert step[0] == "RIGHT" and "beat_misty" in step[1]
    weak = {**goals, "_level": 5}
    step = plan_step(weak, maps, (0x03, 5, 5), "UP")
    assert step[0] == "UP" and "Route 24" in step[1] and "beat_misty" in step[1]
    assert plan_step(weak, maps, (0x23, 3, 9), "UP") is None  # roam the grass


def test_after_misty_push_north_then_east(tmp_path):
    maps = _mem(tmp_path)
    goals = {**BEFORE, "heal_cerulean": True, "beat_misty": True, "_hp": (40, 40), "_level": 20, "_train_level": 8}
    step = plan_step(goals, maps, (0x03, 5, 5), "UP")  # Route 24 already learned: walk to it
    assert step[0] == "UP" and "nugget_bridge" in step[1]
    goals["nugget_bridge"] = True
    assert "to_bill" in plan_step(goals, maps, (0x23, 3, 9), "UP")[1]


def test_mt_moon_floors_are_left_to_exploration(tmp_path):
    maps = _mem(tmp_path)
    goals = {g: True for g in GOALS[:GOALS.index("to_mt_moon") + 1]}
    goals.update({"_hp": (40, 40), "_level": 20, "_train_level": 8})
    assert plan_step(goals, maps, (0x3B, 3, 3), "UP") is None


def test_pokecenter_is_left_not_explored(tmp_path):
    maps = _mem(tmp_path)
    goals = {g: True for g in GOALS[:GOALS.index("buy_magikarp") + 1]}
    goals.update({"_hp": (40, 40), "_level": 20, "_train_level": 8})
    assert plan_step(goals, maps, (0x44, 3, 5), "UP") == ("DOWN", "goal to_mt_moon: walking out of the Pokecenter by its door")
    assert plan_step(goals, maps, (0x44, 6, 5), "UP")[0] == "LEFT"


def test_back_into_the_cave_when_the_crossing_is_unmet(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    for x in (10, 11):
        mem.m(0x0F)["visited"][f"{x},5"] = 1
    mem.m(0x3B)["visited"]["14,35"] = 1
    mem.m(0x0F)["warps"]["11,5,RIGHT"] = [0x3B, 14, 35]
    goals = {g: True for g in GOALS[:GOALS.index("mt_moon_b2f") + 1]}
    goals.update({"_hp": (40, 40), "_level": 20, "_train_level": 8})
    step = plan_step(goals, mem.data["maps"], (0x0F, 10, 5), "RIGHT")
    assert step[0] == "RIGHT" and "through_mt_moon" in step[1] and "Mt Moon 1F" in step[1]
