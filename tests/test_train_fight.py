"""A lead that is deliberately levelling fights wild battles it can win instead of fleeing them (2026-11-07 grind drill:
11 of 13 wild fights fled at 8/23 HP, 17.6 XP/min against a prior of 80)."""
from __future__ import annotations

from pokeagent.explorer.behaviours import Battle

from test_explorer_behaviours import BATTLE, make_ctx, put_box

LEAD_LEVEL, ENEMY_LEVEL = 0xD18C, 0xCFF3


def wild(tmp_path, hp=8, mx=23, lead=7, enemy=3, train_need=8, drill=None):
    ctx = make_ctx(tmp_path, memory={0xD16C: 0, 0xD16D: hp, 0xD18D: 0, 0xD18E: mx, LEAD_LEVEL: lead, ENEMY_LEVEL: enemy})
    ctx.emu.set(BATTLE, 1)
    ctx.train_need = train_need
    ctx.opts.drill_grind = drill
    put_box(ctx, menu=True, text_rows=(" RUN",))   # the cursor sits on RUN: a flee would press A
    ctx.refresh()
    return ctx


def test_training_lead_fights_a_weaker_wild_mon_at_35_percent(tmp_path):
    ctx = wild(tmp_path)                           # L7 lead, 8/23 HP, L3 wild, train target 8
    assert Battle().step(ctx) is None and ctx.bv is not None


def test_training_lead_flees_when_hp_is_under_the_floor(tmp_path):
    dec = Battle().step(wild(tmp_path, hp=3))      # 3/23 is under the 25% fight floor
    assert dec is not None and dec.rule == "flee_run"


def test_training_lead_flees_a_badly_over_level_enemy(tmp_path):
    dec = Battle().step(wild(tmp_path, hp=8, enemy=12))   # 35% HP, L12 wild against an L7 lead
    assert dec is not None and dec.rule == "flee_run"


def test_not_training_is_unchanged(tmp_path):
    dec = Battle().step(wild(tmp_path, train_need=0))      # no training target: the weak rule flees as before
    assert dec is not None and dec.rule == "flee_run"
    assert Battle().step(wild(tmp_path, hp=20, train_need=0)) is None   # healthy: fights as before


def test_a_grind_drill_counts_as_training(tmp_path):
    assert Battle().step(wild(tmp_path, train_need=0, drill=12)) is None
