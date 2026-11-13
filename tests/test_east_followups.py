"""Review follow-ups: disabled-move handling, centre intent, per-stage training levels, heal_cerulean = healed."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.battle import BattleView
from pokeagent.explorer.behaviours.battle_moves import BattleMoves
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.training import TRAIN_LEVEL_BY_GOAL, train_level_for
from pokeagent.goals import GOALS, check_goals
from test_battle_types import BATTLE, make_ctx, put_box

BEFORE_MT = {g: True for g in GOALS[:GOALS.index("to_route4") + 1]}


def _battle_ctx(tmp_path, rows):
    ctx = make_ctx(tmp_path, memory={BATTLE: 1, 0xCFE5: 25, 0xCFE7: 20, 0xCFF3: 3, 0xCFF5: 30})
    put_box(ctx, rows)
    ctx.bv = BattleView(kind=1, hp=10, mx=20, species=25, my_sp=4, my_lvl=5, e_lvl=3, cur=">FIGHT")
    ctx.refresh()
    return ctx


def test_disabled_move_steps_the_cursor_off_and_remembers_it(tmp_path):
    ctx = _battle_ctx(tmp_path, ("disabled!", "TACKLE", "GROWL", "LEECH SEED", ">VINE WHIP"))
    d = BattleMoves().step(ctx)
    assert (d.button, d.rule) == ("UP", "disabled_move")
    assert "VINE WHIP" in ctx.no_pp


def test_disabled_text_with_a_menu_cursor_is_not_a_move(tmp_path):
    for cursor in (">ITEM", ">RUN", ">PKMN"):
        ctx = _battle_ctx(tmp_path, ("The move is disabled!", cursor))
        d = BattleMoves().step(ctx)
        assert d.rule != "disabled_move" and not ctx.no_pp


def _hp(emu, hp, mx, n=1):
    emu.set(0xD163, n)
    for i in range(n):
        base = 0x2C * i
        emu.set(0xD16C + base, hp >> 8); emu.set(0xD16D + base, hp & 255)
        emu.set(0xD18D + base, mx >> 8); emu.set(0xD18E + base, mx & 255)


def test_heal_cerulean_needs_a_full_party_inside_the_center():
    emu, st = FakeEmulator({0xD35E: 0x40}), {}
    _hp(emu, 10, 40, 2)
    assert not check_goals(emu, st)["heal_cerulean"]
    _hp(emu, 40, 40, 2); emu.set(0xD16C + 0x2C, 0); emu.set(0xD16D + 0x2C, 5)  # the second Pokemon still hurt
    assert not check_goals(emu, st)["heal_cerulean"]
    _hp(emu, 40, 40, 2)
    assert check_goals(emu, st)["heal_cerulean"]
    emu.set(0xD35E, 0x03); _hp(emu, 1, 40)
    assert check_goals(emu, st)["heal_cerulean"]  # sticky once done


def test_nurse_is_visited_while_heal_cerulean_is_open(tmp_path):
    goals = {g: True for g in GOALS[:GOALS.index("to_cerulean") + 1]}
    goals.update({"_hp": (38, 40), "_level": 20, "_train_level": 8})
    maps = MapMemory(tmp_path / "m.json").data["maps"]
    assert plan_step(goals, maps, (0x40, 3, 5), "UP")[0] == "UP"
    assert plan_step(goals, maps, (0x40, 3, 2), "UP")[0] == "A"
    assert plan_step(goals, maps, (0x40, 5, 5), "UP")[0] == "LEFT"


def test_center_intent_blocks_the_walk_out(tmp_path):
    maps = MapMemory(tmp_path / "m.json").data["maps"]
    goals = {**BEFORE_MT, "_hp": (40, 40), "_level": 20, "_train_level": 8}
    assert plan_step(goals, maps, (0x44, 3, 5), "UP")[0] == "DOWN"
    assert plan_step({**goals, "_center_intent": "buy MAGIKARP"}, maps, (0x44, 3, 5), "UP") is None


def test_training_levels_come_from_one_table_with_the_cli_floor():
    assert {g: TRAIN_LEVEL_BY_GOAL[g] for g in ("beat_brock", "to_mt_moon", "beat_misty")} == {"beat_brock": 12, "to_mt_moon": 14, "beat_misty": 20}
    pre_brock = {g: True for g in GOALS[:GOALS.index("to_gym") + 1]}
    assert train_level_for(pre_brock, 8) == 12
    assert train_level_for(BEFORE_MT, 8) == 14           # to_mt_moon is next
    assert train_level_for({g: True for g in GOALS[:GOALS.index("to_cerulean") + 1]}, 8) == 20
    assert train_level_for({g: True for g in GOALS}, 8) == 8
    assert train_level_for(BEFORE_MT, 30) == 30           # a higher CLI flag wins


def test_weak_lead_trains_on_route3_before_the_cave(tmp_path):
    mem = MapMemory(tmp_path / "m.json")
    for m in (0x0E, 0x0F):
        mem.m(m)["visited"]["3,3"] = 1
    mem.m(0x0F)["visited"]["3,4"] = 1
    mem.m(0x0F)["warps"]["3,4,DOWN"] = [0x0E, 3, 3]
    goals = {**BEFORE_MT, "_hp": (40, 40), "_level": 9, "_train_level": 14}
    s = plan_step(goals, mem.data["maps"], (0x0F, 3, 4), "UP")
    assert s and "train" in s[1] and "Route 3" in s[1]
    assert plan_step(goals, mem.data["maps"], (0x0E, 3, 3), "UP") is None  # roam the grass
    assert plan_step({**goals, "_level": 15}, mem.data["maps"], (0x0F, 3, 4), "UP") is None  # strong: on to the cave


def test_weak_lead_train_gate_honours_survives_over_hp(tmp_path):
    mem = MapMemory(tmp_path / "m.json")
    for m in (0x0E, 0x0F):
        mem.m(m)["visited"]["3,3"] = 1
    mem.m(0x0F)["visited"]["3,4"] = 1
    mem.m(0x0F)["warps"]["3,4,DOWN"] = [0x0E, 3, 3]
    base = {**BEFORE_MT, "_level": 9, "_train_level": 14}
    maps = mem.data["maps"]
    train = lambda g: (plan_step(g, maps, (0x0F, 3, 4), "UP") or ("", ""))[1]
    assert "Route 3 to train" in train({**base, "_hp": (4, 40), "_survives": True})
    assert "Route 3 to train" not in train({**base, "_hp": (40, 40), "_survives": False})
    assert "Route 3 to train" in train({**base, "_hp": (40, 40)})        # key absent: the 0.5 fraction
    assert "Route 3 to train" not in train({**base, "_hp": (10, 40)})
