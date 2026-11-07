"""S.S. Anne captain segment (2026-11-06): 0 of 55 from the 2F checkpoint. With no plan past ss_ticket the frontier ran east
down the 2F corridor into the rival, lost with a lone starter, blacked out to Cerulean and stalled in its gym. The planner
now walks the learned warps (2F stairs -> 3F deck -> bow) toward the captain."""
from __future__ import annotations

from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS

DONE = {g: True for g in GOALS[:GOALS.index("ss_anne_2f") + 1]}
NOW = {**DONE, "_hp": (40, 40), "_level": 30, "_train_level": 8, "_sprites": []}


def _ship(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    for y in range(4, 12):
        mem.visit(0x60, 2, y, 1)
    for x in range(2, 20):
        mem.visit(0x60, x, 12, 1)
    mem.m(0x60)["warps"]["2,11,DOWN"] = [0x61, 19, 3]
    for x in range(0, 20):
        mem.visit(0x61, x, 3, 1)
    mem.m(0x61)["warps"]["0,3,LEFT"] = [0x63, 13, 6]
    mem.visit(0x63, 13, 6, 1)
    return mem.data["maps"]


def test_2f_walks_to_the_stairs_not_east(tmp_path):
    maps = _ship(tmp_path)
    step = plan_step(NOW, maps, (0x60, 2, 4), "DOWN")
    assert step and step[0] == "DOWN" and "toward it over the learned world" in step[1], step
    step = plan_step(NOW, maps, (0x60, 8, 12), "RIGHT")  # already east on the corridor: come back west
    assert step and step[0] == "LEFT", step


def test_deck_walks_to_the_bow(tmp_path):
    step = plan_step(NOW, _ship(tmp_path), (0x61, 19, 3), "UP")
    assert step and step[0] == "LEFT", step


def test_bow_and_captain_done_are_left_alone(tmp_path):
    maps = _ship(tmp_path)
    assert plan_step(NOW, maps, (0x63, 13, 6), "UP") is None
    assert plan_step({**NOW, "ss_anne_captain": True}, maps, (0x60, 2, 4), "DOWN") is None


def test_vermilion_checkpoint_heals_when_respawn_is_behind(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    for x in range(3, 8):
        mem.visit(0x05, x, 10, 1)
    mem.m(0x05)["warps"]["7,10,UP"] = [0x59, 3, 7]
    mem.visit(0x59, 3, 7, 1)
    maps = mem.data["maps"]
    goals = {**DONE, "to_vermilion": True, "to_ss_anne": False, "_hp": (40, 40), "_level": 30, "_train_level": 8, "_sprites": [], "_respawn": 0x03}
    step = plan_step(goals, maps, (0x05, 3, 10), "UP")
    assert step and step[0] == "RIGHT" and "checkpoint" in step[1], step
    assert plan_step({**goals, "_respawn": 0x05}, maps, (0x05, 3, 10), "UP") is None   # respawn already here
    assert plan_step({**goals, "_ckpt_steps": {5: 150}}, maps, (0x05, 3, 10), "UP") is None  # capped
    step = plan_step(goals, maps, (0x59, 3, 4), "UP")  # at the counter column, walking up
    assert step and step[0] == "UP", step
    step = plan_step(goals, maps, (0x59, 3, 2), "UP")
    assert step and step[0] == "A", step
    # healed (respawn here): walk out of the center instead of exploring it
    step = plan_step({**goals, "_respawn": 0x05}, maps, (0x59, 3, 4), "UP")
    assert step and step[1].startswith("goal checkpoint: crossing") is False and step[0] in ("DOWN", "LEFT", "RIGHT"), step
    assert plan_step({**goals, "_respawn": 0x05, "_center_intent": "restock"}, maps, (0x59, 3, 4), "UP") is None
