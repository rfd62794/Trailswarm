"""Catch-move pick without a damaging move, the readiness clamp, and the grind budget that lifts the training gate."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokeagent.explorer import training
from pokeagent.explorer.behaviours.battle_moves import pick_catch_move
from pokeagent.explorer.grind import (GRIND_BATTLES, GRIND_BLACKOUTS, GRIND_STEPS, GrindBudget, record_battle_result)
from pokeagent.knowledge import kb as kbmod
from test_knowledge import BOSS, SYN, _starter  # noqa: F401  (the synthetic Brock-shaped cartridge)


def _pick(scores: dict, pool: list):
    norm = lambda s: s.upper().replace(" ", "")
    tags = {norm(k): v[1] for k, v in scores.items()}
    return pick_catch_move(pool, tags, lambda mv: scores[mv][0], norm)


def test_catch_pick_prefers_status_then_weakest_hit_then_first_move():
    sc = {"SLEEP POWDER": (70.0, "x [catch-status]"), "TACKLE": (30.0, "t"), "EMBER": (50.0, "e")}
    assert _pick(sc, list(sc)) == ("SLEEP POWDER", "status before the catch")
    assert _pick(sc, ["TACKLE", "EMBER"]) == ("TACKLE", "weakest hit, catching")


def test_catch_pick_with_only_a_heal_usable_does_not_raise():
    sc = {"RECOVER": (40.0, "RECOVER x1 [heal]"), "TACKLE": (0.0, "t"), "EMBER": (0.0, "e")}   # damaging moves are out of PP
    assert _pick(sc, ["RECOVER"]) == ("RECOVER", "no damaging move usable: first move")


def test_readiness_is_clamped_to_the_table_plus_five_and_logged(monkeypatch):
    goals = {g: True for g in training.GOALS[:training.GOALS.index("to_gym") + 1]}   # next boss: BROCK
    monkeypatch.setattr(kbmod, "ROM_KB", {**SYN, "trainers": {"BROCK": [[[12, "PEBBLE"], [14, "PEBBLE"]]]}})
    monkeypatch.setattr(training, "TRAIN_LEVEL_BY_GOAL", {"beat_brock": 8, "to_mt_moon": 14, "beat_misty": 20})
    training._cache.clear()
    weak = _starter("BLAZE", 8, ["TACKLE"])
    raw = training.readiness_for(goals, [weak]).required
    assert raw > 13                                                       # the unclamped verdict is above 8 + 5
    level, note = training.required_level(goals, 8, [weak])
    assert level == 13 and note == f"clamp L{raw} -> L13 vs BROCK: consider a counter catch"
    assert training.train_level_for(goals, 8, [weak]) == 13
    assert training.train_level_for(goals, 40, [weak]) == 40              # --train-level stays a floor above the clamp
    water = at = _starter("AQUA", 8, ["TACKLE", "WATER GUN"])
    assert training.required_level(goals, 8, [water])[1] == ""            # no clamp when the verdict is within the cap


def test_budget_lifts_after_n_battles_without_a_level_gain():
    b = GrindBudget()
    assert b.update("beat_brock", level=8, step=0, battles=0, blackouts=0, training=True) is None
    assert b.update("beat_brock", level=8, step=100, battles=GRIND_BATTLES - 1, blackouts=0, training=True) is None
    why = b.update("beat_brock", level=8, step=200, battles=GRIND_BATTLES, blackouts=0, training=True)
    assert why and f"{GRIND_BATTLES} battles" in why and b.lifted("beat_brock")
    assert b.update("beat_brock", level=8, step=300, battles=GRIND_BATTLES + 1, blackouts=0, training=True) is None   # logged once


def test_a_level_gain_resets_the_battle_and_step_counters():
    b = GrindBudget()
    b.update("beat_brock", level=8, step=0, battles=0, blackouts=0, training=True)
    b.update("beat_brock", level=8, step=1000, battles=GRIND_BATTLES - 2, blackouts=0, training=True)
    b.update("beat_brock", level=9, step=1001, battles=GRIND_BATTLES - 2, blackouts=0, training=True)      # +1 level
    assert b.update("beat_brock", level=9, step=1500, battles=GRIND_BATTLES + 5, blackouts=0, training=True) is None
    assert not b.lifted("beat_brock")


def test_budget_lifts_after_m_training_steps_but_only_training_steps_count():
    b = GrindBudget()
    b.update("beat_misty", level=15, step=0, battles=0, blackouts=0, training=False)
    assert b.update("beat_misty", level=15, step=GRIND_STEPS * 2, battles=0, blackouts=0, training=False) is None   # walking, not grinding
    assert b.update("beat_misty", level=15, step=GRIND_STEPS * 2 + 10, battles=0, blackouts=0, training=True) is None
    why = b.update("beat_misty", level=15, step=GRIND_STEPS * 3 + 10, battles=0, blackouts=0, training=True)
    assert why and f"{GRIND_STEPS} steps" in why


def test_ceiling_rule_keeps_brock_grinding_for_a_l8_lead_and_lifts_for_a_l12_lead():
    b = GrindBudget()
    # Route 1 tops out at L5: a L8 lead still gains XP there (8 < 5 + 6), whatever level is required
    assert b.update("beat_brock", level=8, step=0, battles=0, blackouts=0, training=True, ceiling=5) is None
    assert not b.lifted("beat_brock")
    why = GrindBudget().update("beat_brock", level=12, step=0, battles=0, blackouts=0, training=True, ceiling=5)
    assert why and "ceiling L5" in why


def test_budget_lifts_after_two_blackouts_in_a_row():
    b = GrindBudget()
    assert b.update("to_mt_moon", level=10, step=0, battles=0, blackouts=GRIND_BLACKOUTS - 1, training=True) is None
    why = b.update("to_mt_moon", level=10, step=1, battles=0, blackouts=GRIND_BLACKOUTS, training=True)
    assert why and "blackouts" in why


def test_record_battle_result_counts_blackouts_in_a_row_and_a_win_resets():
    ctx = SimpleNamespace(blackouts_row=0)
    record_battle_result(ctx, won=False, moved_away=True)
    record_battle_result(ctx, won=False, moved_away=False)      # a flee changes nothing
    assert ctx.blackouts_row == 1
    record_battle_result(ctx, won=False, moved_away=True)
    assert ctx.blackouts_row == 2
    record_battle_result(ctx, won=True, moved_away=False)
    assert ctx.blackouts_row == 0


def test_wild_level_ceiling_comes_from_the_drained_grass_table():
    from pokeagent.knowledge import encounters
    kb = {"wild_by_map": {12: {"grass_rate": 25, "water_rate": 0, "grass": [[3, "PIDGEY"]] * 9 + [[5, "RATTATA"]]}}}
    assert encounters.level_ceiling("beat_brock", kb) == 5
    assert encounters.level_ceiling("beat_misty", kb) is None            # unknown route: no ceiling rule


def test_plan_goal_lifts_the_gate_when_the_budget_is_spent_and_logs_it(monkeypatch):
    monkeypatch.setattr(kbmod, "ROM_KB", None)                                        # no ceiling rule: only the battle budget
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.goals import GOALS
    goals = {g: True for g in GOALS[:GOALS.index("to_gym") + 1]}                      # next stage: BROCK
    logs = []
    emu = SimpleNamespace(read=lambda a: 8, read_range=lambda a, n: bytes(n))        # lead level 8, no Magikarp
    ctx = SimpleNamespace(emu=emu, step=0, battles=0, blackouts_row=0, grind=None, log=lambda t, tag=None: logs.append(t))
    assert PlanGoal._budgeted(ctx, goals, 12, None) == 12
    ctx.step, ctx.battles = 300, GRIND_BATTLES
    assert PlanGoal._budgeted(ctx, goals, 12, None) == 0
    assert any("grind budget spent for beat_brock" in t and "lifting the training gate" in t for t in logs)
    assert PlanGoal._budgeted(ctx, goals, 12, None) == 0                              # stays lifted for that goal


def test_budget_tracks_the_strongest_slot_not_a_weak_lead(monkeypatch):
    """Run explore-20261111-214628: lead slot L4, Charmander L12 behind it: the budget saw 'stuck at L4' and lifted the gate."""
    from pokeagent.explorer.grind import best_level, stall_keeps_hold
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.goals import GOALS
    monkeypatch.setattr(kbmod, "ROM_KB", None)
    assert best_level(4, [SimpleNamespace(level=4), SimpleNamespace(level=12)]) == 12
    assert best_level(4, None) == 4
    goals = {g: True for g in GOALS[:GOALS.index("to_gym") + 1]}
    ctx = SimpleNamespace(emu=SimpleNamespace(read=lambda a: 4, read_range=lambda a, n: bytes(n)), step=0, battles=0,
                          blackouts_row=0, grind=None, log=lambda t, tag=None: None)
    party = [SimpleNamespace(level=4), SimpleNamespace(level=12)]
    PlanGoal._budgeted(ctx, goals, 17, None, party)
    ctx.step = 100
    party[1].level = 13                                                    # the strong slot levels: progress, window resets
    PlanGoal._budgeted(ctx, goals, 17, None, party)
    ctx.step = GRIND_STEPS - 1
    assert PlanGoal._budgeted(ctx, goals, 17, None, party) == 17


def test_stall_lift_keeps_the_gym_hold_but_ceiling_and_blackouts_release_it():
    from pokeagent.explorer.grind import stall_keeps_hold
    assert stall_keeps_hold("2500 steps without a level gain (stuck at L12)")
    assert stall_keeps_hold("25 battles without a level gain (stuck at L12)")
    assert not stall_keeps_hold("lead L20 is 6+ levels above the route's wild ceiling L5: no XP left to grind")
    assert not stall_keeps_hold("2 blackouts in a row while training")
    assert not stall_keeps_hold("")


def test_stall_hold_releases_after_the_cap_or_on_a_blackout():
    from pokeagent.explorer.grind import STALL_HOLD_CAP, stall_hold_holds
    why = "2500 steps without a level gain (stuck at L12)"
    st = {}
    assert stall_hold_holds(st, why, 1000, 0)
    assert stall_hold_holds(st, why, 1000 + STALL_HOLD_CAP - 1, 0)
    assert not stall_hold_holds(st, why, 1000 + STALL_HOLD_CAP, 0)            # the held stall eventually releases
    st = {}
    assert stall_hold_holds(st, why, 50, 0)
    assert not stall_hold_holds(st, why, 60, 1)                               # a blackout while held releases it
    assert not stall_hold_holds({}, "2 blackouts in a row while training", 0, 0)


def test_magikarp_trainee_keeps_the_gated_lead_measure(monkeypatch):
    """Fighter L30 + Magikarp L5: lead_level = min(30, 5+gap), not the max slot; trainee gains must reset the budget."""
    from pokeagent.explorer.behaviours import plan_goal as pg
    from pokeagent.goals import GOALS
    monkeypatch.setattr(kbmod, "ROM_KB", None)
    monkeypatch.setattr(pg, "trainee_slot", lambda emu: 1)
    monkeypatch.setattr(pg, "lead_level", lambda emu: 8)
    goals = {g: True for g in GOALS[:GOALS.index("to_gym") + 1]}
    ctx = SimpleNamespace(emu=None, step=0, battles=0, blackouts_row=0, grind=None, log=lambda t, tag=None: None)
    party = [SimpleNamespace(level=30)]
    pg.PlanGoal._budgeted(ctx, goals, 12, None, party)
    assert ctx.grind._s["beat_brock"]["level"] == 8                           # not best_level == 30
