"""Game knowledge: move effects, effect-aware scoring, encounters / trainers queries, party readiness."""
from __future__ import annotations

import pytest

from pokeagent.explorer import training
from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge import encounters, kb as kbmod, trainers
from pokeagent.knowledge.moves import EFFECTS, describe
from pokeagent.knowledge.party import Combatant, at_level, moves_at
from pokeagent.knowledge.readiness import assess, fight
from pokeagent.knowledge.scoring import ScoreCtx, adjust

REAL = kbmod.ROM_KB
needs_kb = pytest.mark.skipif(REAL is None, reason="kb/rom_tables.json (ROM-derived, gitignored) not present")


def _mv(name, typ, power, acc=1.0, effect=0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": effect, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc, "moves1": moves1}


# Two starters with identical stats, one WATER and one FIRE, against a ROCK/GROUND boss (Brock-shaped).
SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40), "3": _mv("EMBER", "FIRE", 40, effect=4)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["FIRE", "ROCK", 0.5]],
    "species_by_dex": {"1": _species("AQUA", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
                       "2": _species("BLAZE", "FIRE", "FIRE", 44, 48, 65, 43, 50, ["TACKLE"]),
                       "3": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"])},
    "learnsets": {"AQUA": {"learnset": [[8, "WATER GUN"]]}, "BLAZE": {"learnset": [[8, "EMBER"]]}, "PEBBLE": {"learnset": []}},
}


def _starter(name, level, moves):
    row = SYN["species_by_dex"]["1" if name == "AQUA" else "2"]
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, (row["type1"],), hp, st, tuple(moves), (8,) * 5, (0,) * 5)


BOSS = [(12, "PEBBLE"), (14, "PEBBLE")]


def test_squirtle_shaped_starter_ready_earlier_than_resisted_one():
    water, fire = _starter("AQUA", 8, ["TACKLE", "WATER GUN"]), _starter("BLAZE", 8, ["TACKLE", "EMBER"])
    rw, rf = assess([water], BOSS, "BROCK", SYN), assess([fire], BOSS, "BROCK", SYN)
    assert rw.required < rf.required
    assert rw.ready and not rf.ready                     # the same level and stats: only the type matchup differs
    assert rw.text == "ready vs BROCK: AQUA L8 WATER x4 vs ROCK/GROUND -> ok"
    assert rf.text.startswith("train to L") and "FIRE x0.5 vs ROCK/GROUND" in rf.text


def test_ready_verdict_and_logged_text_when_the_lead_is_high_enough():
    water = at_level(_starter("AQUA", 8, ["TACKLE", "WATER GUN"]), 20, SYN)
    r = assess([water], BOSS, "BROCK", SYN)
    assert r.ready and r.required == 20
    assert r.text == "ready vs BROCK: AQUA L20 WATER x4 vs ROCK/GROUND -> ok"


def test_stalemate_is_not_a_win_and_missing_data_returns_none():
    wimp = _starter("AQUA", 8, ["GROWL"])
    assert fight([wimp], [__import__("pokeagent.knowledge.party", fromlist=["x"]).trainer_mon("PEBBLE", 12, SYN)], {}, SYN["moves"]) < 0
    assert assess([], BOSS, "BROCK", SYN) is None
    assert assess([_starter("AQUA", 8, ["TACKLE"])], [(12, "NOSUCHMON")], "X", SYN) is None


def test_moves_at_fills_slots_then_pushes_the_oldest_out():
    kb = {"species_by_dex": {"1": {"name": "M", "moves1": ["A", "B"]}},
          "learnsets": {"M": {"learnset": [[5, "C"], [9, "D"], [12, "E"]]}}}
    assert moves_at("M", 4, kb) == ["A", "B"]
    assert moves_at("M", 12, kb) == ["B", "C", "D", "E"]
    assert moves_at("M", 12, kb, after=8) == ["D", "E"]


def test_train_level_uses_party_verdict_with_table_fallback_and_hard_floor(monkeypatch):
    goals = {g: True for g in training.GOALS[:training.GOALS.index("to_gym") + 1]}   # next boss: beat_brock
    monkeypatch.setattr(kbmod, "ROM_KB", {**SYN, "trainers": {"BROCK": [[[12, "PEBBLE"], [14, "PEBBLE"]]]}})
    training._cache.clear()
    water, fire = _starter("AQUA", 8, ["TACKLE", "WATER GUN"]), _starter("BLAZE", 8, ["TACKLE", "EMBER"])
    assert training.train_level_for(goals, 8, [water]) < training.train_level_for(goals, 8, [fire])
    assert training.train_level_for(goals, 8, None) == training.TRAIN_LEVEL_BY_GOAL["beat_brock"]       # no party -> the table
    assert training.train_level_for(goals, 40, [water]) == 40                                              # --train-level is a floor
    monkeypatch.setattr(kbmod, "ROM_KB", None)
    training._cache.clear()
    assert training.train_level_for(goals, 8, [water]) == 12                                               # no data -> the table


def test_scoring_adjusts_by_effect_and_keeps_plain_damage():
    c = ScoreCtx(level=20, hp_frac=0.3, enemy_hp=40)
    assert adjust(_mv("TACKLE", "NORMAL", 35), 33.0, 1.0, 0.95, c) == (33.0, "")
    assert adjust(_mv("SEISMIC TOSS", "FIGHTING", 1, effect=0x29), 1.0, 1.0, 1.0, c)[0] == pytest.approx(20 * 3.5)
    assert adjust(_mv("SOLARBEAM", "GRASS", 120, effect=0x27), 100.0, 1.0, 1.0, c) == (50.0, "two-turn")
    assert adjust(_mv("HYPER BEAM", "NORMAL", 150, effect=0x50), 100.0, 1.0, 1.0, c)[0] == 50.0
    assert adjust(_mv("DOUBLE KICK", "FIGHTING", 30, effect=0x2C), 30.0, 1.0, 1.0, c)[0] == 60.0
    assert adjust(_mv("ABSORB", "GRASS", 20, effect=3), 20.0, 1.0, 1.0, c)[0] == pytest.approx(25.0)      # low HP: the heal counts
    sleep = _mv("SLEEP POWDER", "GRASS", 0, 0.75, 0x20)
    assert adjust(sleep, 0.0, 1.0, 0.75, ScoreCtx(catching=True)) == (70.0, "catch-status")
    assert adjust(sleep, 0.0, 1.0, 0.75, ScoreCtx(catching=True, enemy_status=4))[0] == 0.0           # already asleep
    assert adjust(sleep, 0.0, 1.0, 0.75, ScoreCtx(fast_ko=True))[0] == 0.0                              # the fight ends by damage
    assert adjust(_mv("GROWL", "NORMAL", 0, 1.0, 0x12), 0.0, 1.0, 1.0, ScoreCtx())[0] < 10


def test_encounters_and_trainer_queries_on_a_synthetic_table():
    kb = {"wild_by_map": {12: {"grass_rate": 25, "water_rate": 0, "grass": [[3, "PIDGEY"]] * 5 + [[4, "RATTATA"]] * 5}},
          "trainers": {"BROCK": [[[12, "GEODUDE"], [14, "ONIX"]]]},
          "map_trainers": {54: [{"class": "BROCK", "party": 1, "x": 4, "y": 1}]}}
    assert encounters.where_to_catch("pidgey", kb)[0]["name"] == "Route 1"
    assert encounters.species_on(12, kb)["RATTATA"][:2] == (4, 4)
    assert trainers.what_does_use("brock", kb) == "BROCK: GEODUDE L12, ONIX L14"
    assert trainers.trainers_on(54, kb)[0]["mons"] == [(12, "GEODUDE"), (14, "ONIX")]


@needs_kb
def test_every_rom_effect_id_has_a_table_entry():
    ids = {mv["effect"] for mv in REAL["moves"].values()}
    assert ids <= set(EFFECTS), sorted(hex(i) for i in ids - set(EFFECTS))
    assert all(describe(mv) for mv in REAL["moves"].values())


@needs_kb
def test_rom_facts_drained_from_the_cartridge():
    assert trainers.what_does_use("BROCK") == "BROCK: GEODUDE L12, ONIX L14"
    assert {n for n in encounters.species_on(0x0C)} == {"PIDGEY", "RATTATA"}
    assert "THUNDER WAVE: ELECTRIC status" in describe(next(m for m in REAL["moves"].values() if m["name"] == "THUNDER WAVE"))
    assert REAL["items"]["20"] == {"name": "POTION", "price": 300}
    assert trainers.strongest_on_mt_moon()                      # Mt Moon floors have drainable trainer parties
