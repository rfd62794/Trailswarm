"""party_order.want_home: the matchup lead before a known boss, the exp rotation on a grind.

All fixtures synthetic: ctx is a SimpleNamespace, the party and the boss are Combatants built on a small
SYN table (no ROM, no emulator).
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import party_order as po_mod
from pokeagent.explorer.stats import stat_value
from pokeagent.goals import GOALS
from pokeagent.knowledge import team_plan
from pokeagent.knowledge.party import Combatant

SYN = {
    "moves": {"1": {"name": "EMBER", "type": "FIRE", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "2": {"name": "VINE WHIP", "type": "GRASS", "power": 45, "accuracy": 1.0, "effect": 0, "pp": 25},
              "3": {"name": "WATER GUN", "type": "WATER", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "4": {"name": "TACKLE", "type": "NORMAL", "power": 35, "accuracy": 1.0, "effect": 0, "pp": 35}},
    "type_chart": [["WATER", "FIRE", 2.0], ["GRASS", "WATER", 2.0], ["FIRE", "WATER", 0.5],
                   ["WATER", "GRASS", 0.5]],
    "species_by_dex": {
        "1": {"name": "CHARMELEON", "type1": "FIRE", "type2": "FIRE", "hp": 58, "atk": 64, "def": 58,
              "spd": 80, "spc": 65, "moves1": ["EMBER"]},
        "2": {"name": "ODDISH", "type1": "GRASS", "type2": "POISON", "hp": 45, "atk": 50, "def": 55,
              "spd": 30, "spc": 75, "moves1": ["VINE WHIP"]},
        "3": {"name": "STARYU", "type1": "WATER", "type2": "WATER", "hp": 30, "atk": 45, "def": 55,
              "spd": 85, "spc": 70, "moves1": ["WATER GUN"]},
        "4": {"name": "RATTATA", "type1": "NORMAL", "type2": "NORMAL", "hp": 30, "atk": 56, "def": 35,
              "spd": 72, "spc": 25, "moves1": ["TACKLE"]},
    },
    "learnsets": {},
}

MISTY = [(18, "STARYU")]


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     tuple(row["moves1"]), (8,) * 5, (0,) * 5)


def _ctx(goals_stage="beat_misty", train_need=0):
    met = {g: True for g in GOALS[:GOALS.index(goals_stage)]} if goals_stage in GOALS else {}
    return SimpleNamespace(trainer_target=None, view=SimpleNamespace(m=0x03), train_need=train_need,
                           train_member=None, emu=None, goals=lambda: met)


def _patch(monkeypatch, team, boss=MISTY):
    monkeypatch.setattr(team_plan, "table", lambda kb, k: SYN.get(k, {}))
    monkeypatch.setattr(po_mod, "our_party", lambda emu: team)
    monkeypatch.setattr(po_mod, "trainer_mon", lambda n, lv: _mon(n, lv))
    monkeypatch.setattr(po_mod.trainers, "boss_party", lambda goal, starter_names=(): boss)
    monkeypatch.setattr(po_mod, "lead_level", lambda emu: 20)
    monkeypatch.setattr(po_mod, "species_names", lambda emu: [c.name for c in team])


def test_matchup_lead_leads_before_the_boss(monkeypatch):
    team = [_mon("CHARMELEON", 20), _mon("ODDISH", 20)]
    _patch(monkeypatch, team)
    w = po_mod.want_home(_ctx())
    assert w is not None and (w[0], w[1]) == (1, 0)  # the Grass answer to Staryu leads
    assert "matchup lead" in w[2]


def test_already_ordered_returns_none(monkeypatch):
    team = [_mon("ODDISH", 20), _mon("CHARMELEON", 20)]
    _patch(monkeypatch, team)
    assert po_mod.want_home(_ctx()) is None  # the matchup pick already leads


def test_open_gate_keeps_the_rotation_lead(monkeypatch):
    team = [_mon("CHARMELEON", 20), _mon("RATTATA", 8)]
    _patch(monkeypatch, team)
    monkeypatch.setattr(po_mod, "trainee_slot", lambda emu: None)  # no Magikarp
    monkeypatch.setattr(po_mod, "read_party", lambda emu: team)
    ctx = _ctx(train_need=30)  # still under the gate: grinding, not boss-pushing
    team_plan.of(ctx)["breakers"] = (1,)
    w = po_mod.want_home(ctx)
    assert w is not None and (w[0], w[1]) == (1, 0)
    assert "exp rotation" in w[2]


def test_no_opponent_and_no_breakers_leaves_the_order(monkeypatch):
    team = [_mon("CHARMELEON", 20), _mon("RATTATA", 15)]
    _patch(monkeypatch, team, boss=[])
    monkeypatch.setattr(po_mod, "trainee_slot", lambda emu: None)
    assert po_mod.want_home(_ctx()) is None


# run explore-20261112-072650: Charmander<->Pidgey flipped 12-34 steps apart (matchup lead vs exp rotation).
def _raw(level, species=1, hp=10):
    return SimpleNamespace(species=species, level=level, hp=hp, max_hp=20)


def _rotation_ctx(monkeypatch, raws):
    team = [_mon("CHARMELEON", 20), _mon("RATTATA", 8)]
    _patch(monkeypatch, team, boss=[])
    monkeypatch.setattr(po_mod, "trainee_slot", lambda emu: None)
    monkeypatch.setattr(po_mod, "read_party", lambda emu: raws)
    ctx = _ctx(train_need=30)
    ctx.step, ctx.emu = 100, None
    team_plan.of(ctx)["breakers"] = (1,)
    return ctx


def test_recent_reorder_holds_the_rotation_flip(monkeypatch):
    raws = [_raw(20, 1), _raw(8, 2)]
    ctx = _rotation_ctx(monkeypatch, raws)
    team_plan.of(ctx)["order_hold"] = (ctx.step - 12, po_mod.team_sig(ctx), ())   # a reorder 12 steps ago
    assert po_mod.want_home(ctx) is None
    ctx.step += po_mod.HOLD_STEPS                                              # the hold has expired
    assert po_mod.want_home(ctx) is not None


def test_level_or_faint_change_releases_the_hold(monkeypatch):
    raws = [_raw(20, 1), _raw(8, 2)]
    ctx = _rotation_ctx(monkeypatch, raws)
    team_plan.of(ctx)["order_hold"] = (ctx.step - 12, po_mod.team_sig(ctx), ())
    raws[1] = _raw(9, 2)                                                       # the trainee levelled up
    assert po_mod.want_home(ctx) is not None
    raws[1] = _raw(8, 2, hp=0)                                                 # or fainted
    assert po_mod.want_home(ctx) is not None


def test_recent_reorder_holds_the_matchup_flip(monkeypatch):
    team = [_mon("CHARMELEON", 20), _mon("ODDISH", 20)]
    _patch(monkeypatch, team)
    monkeypatch.setattr(po_mod, "read_party", lambda emu: [_raw(20, 1), _raw(20, 2)])
    ctx = _ctx()
    ctx.step = 100
    team_plan.of(ctx)["order_hold"] = (90, po_mod.team_sig(ctx), po_mod._opp_key(ctx))
    assert po_mod.want_home(ctx) is None


def test_a_different_trainer_releases_the_hold(monkeypatch):
    team = [_mon("CHARMELEON", 20), _mon("ODDISH", 20)]
    _patch(monkeypatch, team)
    monkeypatch.setattr(po_mod, "read_party", lambda emu: [_raw(20, 1), _raw(20, 2)])
    ctx = _ctx()
    ctx.step = 100
    team_plan.of(ctx)["order_hold"] = (90, po_mod.team_sig(ctx), ((10, "RATTATA"),))   # held for trainer A
    assert po_mod.want_home(ctx) is not None                                           # boss/trainer B engaged now


def test_a_weak_lead_releases_the_hold(monkeypatch):
    raws = [_raw(20, 1), _raw(8, 2)]
    ctx = _rotation_ctx(monkeypatch, raws)
    team_plan.of(ctx)["order_hold"] = (ctx.step - 12, po_mod.team_sig(ctx), ())
    assert po_mod.want_home(ctx) is None
    raws[0] = _raw(20, 1, hp=4)                       # 4/20 < SWITCH_MIN_HP, alive: sig unchanged
    assert po_mod.want_home(ctx) is not None
