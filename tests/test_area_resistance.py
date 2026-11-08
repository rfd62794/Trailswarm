"""area_resistance: per-trainer margins, the worst member, the weak_to list, and the area min/mean
on a synthetic cartridge (report only; empty inputs return {})."""
from __future__ import annotations

import pytest

from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge.area_resistance import resistance
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant


def _mv(name, typ, power, acc=1.0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": 0, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc,
            "moves1": moves1}


# AQUA (WATER) sweeps PEBBLE (ROCK/GROUND) but is weak to STINGER's BUG and VINE's GRASS moves.
SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40),
              "3": _mv("BUG BITE", "BUG", 40), "4": _mv("VINE LASH", "GRASS", 40)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["BUG", "WATER", 2.0],
                   ["GRASS", "WATER", 2.0], ["NORMAL", "ROCK", 0.5], ["NORMAL", "GROUND", 1.0]],
    "species_by_dex": {"1": _species("AQUA", "WATER", "WATER", 60, 60, 65, 60, 60, ["TACKLE", "WATER GUN"]),
                       "2": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"]),
                       "3": _species("STINGER", "BUG", "BUG", 45, 60, 40, 70, 30, ["BUG BITE"]),
                       "4": _species("VINE", "GRASS", "GRASS", 50, 55, 45, 55, 50, ["VINE LASH"])},
    "learnsets": {"AQUA": {"learnset": []}, "PEBBLE": {"learnset": []}, "STINGER": {"learnset": []},
                  "VINE": {"learnset": []}},
}


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, (row["type1"],), hp, st, tuple(row["moves1"]), (8,) * 5, (0,) * 5)


CHART = {(a, d): e for a, d, e in SYN["type_chart"]}
TRAINERS = [[(14, "PEBBLE")], [(14, "STINGER"), (15, "VINE")]]


def test_per_trainer_margin_worst_member_and_weak_to():
    res = resistance([_mon("AQUA", 30)], TRAINERS, CHART, SYN["moves"], kb=SYN)
    assert len(res["trainers"]) == 2
    easy, hard = res["trainers"]
    assert easy["margin"] >= 0.30 and easy["worst_member"] == "AQUA" and easy["weak_to"] == []
    assert hard["margin"] < easy["margin"] and "BUG" in hard["weak_to"] and "GRASS" in hard["weak_to"]


def test_area_margin_is_the_minimum_and_mean_is_reported():
    res = resistance([_mon("AQUA", 30)], TRAINERS, CHART, SYN["moves"], kb=SYN)
    margins = [t["margin"] for t in res["trainers"]]
    assert res["area_margin"] == pytest.approx(min(margins))
    assert res["mean_margin"] == pytest.approx(round(sum(margins) / len(margins), 2))
    assert set(res["weak_to"]) == {"BUG", "GRASS"}


def test_weak_party_shows_resistance_failing():
    res = resistance([_mon("AQUA", 6)], TRAINERS, CHART, SYN["moves"], kb=SYN)
    assert res["area_margin"] < 0


def test_empty_inputs_return_an_empty_result():
    assert resistance([], TRAINERS, CHART, SYN["moves"], kb=SYN) == {}
    assert resistance([_mon("AQUA", 30)], [], CHART, SYN["moves"], kb=SYN) == {}
