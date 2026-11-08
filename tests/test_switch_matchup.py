"""SwitchOut.matchup_pick: the matchup switch in a trainer battle (synthetic ctx, no ROM/emulator).
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer.stats import stat_value
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
        "3": {"name": "STARMIE", "type1": "WATER", "type2": "PSYCHIC", "hp": 60, "atk": 75, "def": 85,
              "spd": 115, "spc": 100, "moves1": ["WATER GUN"]},
        "4": {"name": "WEEDLE", "type1": "BUG", "type2": "POISON", "hp": 40, "atk": 35, "def": 30,
              "spd": 50, "spc": 20, "moves1": ["TACKLE"]},
    },
    "learnsets": {},
}


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     tuple(row["moves1"]), (8,) * 5, (0,) * 5)


def _ctx(team, kind=2, switches=0, active_hp=None):
    emu = SimpleNamespace()  # every emu-touching helper is patched below
    return SimpleNamespace(bv=SimpleNamespace(kind=kind), battle_log={"matchup_switches": switches},
                           battles=3, train_member=None, emu=emu, switch_gave_up=None,
                           _team=team, _active_hp=active_hp)


def _patch(monkeypatch, ctx):
    team = ctx._team
    monkeypatch.setattr(team_plan, "table", lambda kb, k: SYN.get(k, {}))
    monkeypatch.setattr(so_mod, "our_party", lambda emu: team)
    monkeypatch.setattr(so_mod, "_foe", lambda c: _mon("STARMIE", 21))
    monkeypatch.setattr(so_mod, "read_battle_mon", lambda emu: SimpleNamespace(party_pos=0))
    hp = [c.hp for c in team]
    if ctx._active_hp is not None:
        hp[0] = ctx._active_hp
    monkeypatch.setattr(so_mod, "read_party", lambda emu: [SimpleNamespace(hp=h) for h in hp])
    monkeypatch.setattr(so_mod, "trainee_slot_for", lambda emu, named: None)


def test_matchup_pick_fires_in_a_trainer_battle(monkeypatch):
    team = [_mon("CHARMELEON", 15), _mon("ODDISH", 16)]
    ctx = _ctx(team)
    _patch(monkeypatch, ctx)
    pick = so_mod.matchup_pick(ctx)
    assert pick is not None and pick[0] == 1          # the Grass answer to Starmie
    assert "thin" in pick[1] or "weak" in pick[1]


def test_matchup_pick_never_in_a_wild_battle(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("ODDISH", 16)], kind=1)
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None


def test_matchup_pick_respects_the_per_battle_cap(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("ODDISH", 16)], switches=2)
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None  # the third switch is never picked


def test_matchup_pick_none_when_nobody_is_better(monkeypatch):
    ctx = _ctx([_mon("CHARMELEON", 15), _mon("WEEDLE", 9)])
    _patch(monkeypatch, ctx)
    assert so_mod.matchup_pick(ctx) is None
