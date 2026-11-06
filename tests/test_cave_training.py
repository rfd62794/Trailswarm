"""Mt Moon is trained for OUTSIDE (Route 3) at the Mt Moon table (cap table+5), never inside, and never as Misty's L24.

2026-11-05: to_mt_moon lands on entering 1F, so with mt_moon_b1f next the stage read as beat_misty (need L24) and
agents grinded wild Zubat/Magikarp fights on 1F for thousands of presses.
"""
from __future__ import annotations

import pytest

from pokeagent.explorer import training
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.planner_east import CAVE
from pokeagent.explorer.world import DUNGEON_MAPS, MT_MOON_MAPS
from pokeagent.goals import GOALS


def _met(upto: str) -> dict:
    return {g: True for g in GOALS[:GOALS.index(upto) + 1]}


@pytest.mark.parametrize("last_met", ["to_mt_moon", "mt_moon_b1f", "mt_moon_b2f"])
def test_cave_floors_belong_to_the_mt_moon_stage_not_misty(last_met):
    assert training.stage_goal(_met(last_met)) == "to_mt_moon"
    need, _ = training.required_level(_met(last_met), 8, None)
    assert need == training.TRAIN_LEVEL_BY_GOAL["to_mt_moon"]


def test_misty_stage_still_starts_after_the_cave():
    assert training.stage_goal(_met("through_mt_moon")) == "beat_misty"


def test_dungeon_set_is_the_three_mt_moon_floors():
    assert DUNGEON_MAPS == MT_MOON_MAPS == {0x3B, 0x3C, 0x3D} and set(CAVE) == set(DUNGEON_MAPS)


def test_no_training_gate_inside_the_cave_only_outside():
    assert [training.gate_for(m, 19) for m in (0x3B, 0x3C, 0x3D)] == [0, 0, 0]
    assert [training.gate_for(m, 19) for m in (0x0E, 0x0F, 0x44, 0x02)] == [19] * 4


def _plan(tmp_path, pos, last_met="to_mt_moon", level=10, hp=(30, 30)):
    maps = MapMemory(tmp_path / "m.json").data["maps"]
    goals = {**_met(last_met), "_hp": hp, "_level": level, "_train_level": 14}
    return plan_step(goals, maps, pos, "UP")


def test_outside_the_cave_a_weak_lead_is_sent_back_to_route_3_for_every_mt_moon_stage(tmp_path):
    # Route 4 (0x0F): not Route 3, so the planner must head back (None only if the world graph has no path)
    for last in ("to_mt_moon", "mt_moon_b1f"):
        r = _plan(tmp_path, (0x0F, 5, 5), last)
        assert r is None or "Route 3" in r[1] or "train" in r[1]


def test_inside_the_cave_the_planner_never_walks_out_to_train(tmp_path):
    for floor in sorted(DUNGEON_MAPS):
        r = _plan(tmp_path, (floor, 5, 5), "to_mt_moon", level=10)
        assert r is None or "Route 3" not in r[1]


def test_battle_presses_do_not_feed_the_stuck_loop_detector(tmp_path):
    """200 presses of battle text on one tile are a fight, not a loop; shaking after it random-walked into more fights."""
    from pokeagent.explorer.behaviours.guards import LoopGuard
    from test_battle_types import BATTLE, make_ctx
    ctx = make_ctx(tmp_path, memory={BATTLE: 1})
    for _ in range(200):
        ctx.refresh()
        LoopGuard().step(ctx)
    ctx.emu.set(BATTLE, 0)
    ctx.refresh()
    assert LoopGuard().step(ctx) is None and ctx.shake == 0 and ctx.shakes == 0
    for _ in range(150):  # the same 200 presses outside a fight still count (a real overworld loop)
        ctx.refresh()
        LoopGuard().step(ctx)
    assert ctx.shakes >= 1
