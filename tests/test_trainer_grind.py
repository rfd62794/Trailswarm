"""Trainers as one-time grind options: trainer_xp, rank_trainer_grinds ordering and filters,
the prize->XP conversion, and the grind report's 'trainers worth saving or taking' section."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from pokeagent.explorer import trainer_ledger as T
from pokeagent.explorer.stats import stat_value
from pokeagent.grind import trainer_spots as G
from pokeagent.grind.atlas import PRIOR_BATTLE_STEPS
from pokeagent.grind.xpmath import xp_gain
from pokeagent.knowledge.party import Combatant

ROOT = Path(__file__).resolve().parents[1]


def _mv(name, typ, power, acc=1.0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": 0, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc,
            "moves1": moves1}


SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40), "3": _mv("EMBER", "FIRE", 40)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["FIRE", "ROCK", 0.5]],
    "species_by_dex": {"1": _species("AQUA", "WATER", "WATER", 60, 60, 65, 60, 60, ["TACKLE", "WATER GUN"]),
                       "2": _species("BLAZE", "FIRE", "FIRE", 44, 48, 65, 43, 50, ["TACKLE", "EMBER"]),
                       "3": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"])},
    "learnsets": {"AQUA": {"learnset": []}, "BLAZE": {"learnset": []}, "PEBBLE": {"learnset": []}},
    "trainers": {"LASS": [[[14, "PEBBLE"], [15, "PEBBLE"]]]},
    "trainer_money": {"LASS": 15},
}


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, (row["type1"],), hp, st, tuple(row["moves1"]), (8,) * 5, (0,) * 5)


STRONG = [_mon("AQUA", 30)]
WEAK = [_mon("BLAZE", 5)]
BASE_EXP = {"PEBBLE": 86}

ROWS = [{"class": "LASS", "party": 1, "x": 10, "y": 22, "mons": [(14, "PEBBLE"), (15, "PEBBLE")]},
        {"class": "LASS", "party": 1, "x": 11, "y": 28, "mons": [(14, "PEBBLE")]}]


def test_trainer_xp_sums_xp_gain_with_the_trainer_bonus():
    mons = [(14, "PEBBLE"), (15, "PEBBLE")]
    want = xp_gain(86, 14, trainer=True) + xp_gain(86, 15, trainer=True)
    assert G.trainer_xp(mons, BASE_EXP) == pytest.approx(want)


def _rank(party=STRONG, spots=None, beaten=()):
    led = T.TrainerLedger({35: ROWS})
    for i in beaten:
        led.mark_beaten(35, i, "battle_log", 1)
    return G.rank_trainer_grinds(led, 35, party, BASE_EXP, SYN, spots if spots is not None else [], kb=SYN)


def test_rank_orders_by_xp_per_step_and_converts_the_prize():
    grinds = _rank(spots=lambda x, y: 10.0 if (x, y) == (10, 22) else 50.0)
    assert [g.entry.idx for g in grinds] == [0, 1]
    g0 = grinds[0]
    assert g0.steps == PRIOR_BATTLE_STEPS + 10
    assert g0.prize == 15 * 15                                   # base money x last mon's level
    assert g0.value == pytest.approx(g0.xp + g0.prize * G.YEN_PER_XP)
    assert g0.xp_per_step == pytest.approx(g0.value / g0.steps)


def test_grinds_the_sim_loses_and_beaten_trainers_are_dropped():
    assert _rank(party=WEAK) == []                                # never walk into a loss
    grinds = _rank(beaten=[0])
    assert [g.entry.idx for g in grinds] == [1]                   # one-time: beaten is gone


def _grind_report():
    spec = importlib.util.spec_from_file_location("grind_report_tool", ROOT / "tools" / "grind_report.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_report_prints_the_trainer_section(capsys):
    gr = _grind_report()
    led = T.TrainerLedger({35: ROWS})
    wild = [{"xp_per_step": 0.01, "name": "Route 24"}]
    gr.print_trainer_section(35, "Route 24", led, STRONG, BASE_EXP, SYN, wild, kb=SYN)
    out = capsys.readouterr().out
    assert "trainers worth saving or taking" in out and "LASS p1" in out
    assert "area resistance (Route 24, 2 trainers): min margin" in out
