"""team_value: member_value's boss gain / dex / catcher / cost terms, form_at, candidates_for, pokedex_value."""
from __future__ import annotations

import math

import pytest

from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge.party import Combatant
from pokeagent.knowledge.team_value import (CATCHER_VALUE, DEX_FLOOR_VALUE, DEX_GATE_VALUE, TRAINEE_SHARE,
                                            Candidate, candidates_for, catcher_value, fights_to_reach, form_at,
                                            member_value, pokedex_value, qualifies_catcher)
from pokeagent.grind.xpmath import xp_needed


def _mv(name, typ, power, acc=1.0, effect=0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": effect, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1, growth="MEDIUM_SLOW", catch_rate=200, base_exp=60):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc,
            "moves1": moves1, "growth": growth, "catch_rate": catch_rate, "base_exp": base_exp}


SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40),
              "3": _mv("SPLASH", "NORMAL", 0), "4": _mv("SING", "NORMAL", 0, 0.55, effect=0x20)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["WATER", "WATER", 0.5]],
    "species_by_dex": {
        "1": _species("AQUA", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
        "2": _species("BLAZE", "FIRE", "FIRE", 44, 48, 65, 43, 50, ["TACKLE"]),
        "3": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"]),
        "4": _species("MAGIKARP", "WATER", "WATER", 15, 5, 40, 50, 10, ["SPLASH"], growth="SLOW", catch_rate=255, base_exp=20),
        "5": _species("GYARADOS", "WATER", "FLYING", 95, 125, 79, 81, 100, ["TACKLE"], growth="SLOW", catch_rate=45, base_exp=214),
        "6": _species("PIDGEY", "NORMAL", "FLYING", 30, 25, 40, 40, 30, ["TACKLE"], growth="MEDIUM_FAST"),
        "7": _species("SINGER", "NORMAL", "NORMAL", 40, 30, 30, 30, 30, ["SING"]),
        "8": _species("SQUIRTLE", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
        "9": _species("WARTORTLE", "WATER", "WATER", 59, 63, 80, 58, 65, ["TACKLE"]),
        "10": _species("BLASTOISE", "WATER", "WATER", 79, 83, 100, 78, 85, ["TACKLE"]),
        "11": _species("BULBASAUR", "GRASS", "POISON", 45, 49, 49, 45, 65, ["TACKLE"]),
        "12": _species("CHARMANDER", "FIRE", "FIRE", 39, 52, 43, 65, 50, ["TACKLE"]),
        "13": _species("NIDORAN(M)", "POISON", "POISON", 46, 57, 40, 50, 40, ["TACKLE"], catch_rate=235, base_exp=60),
    },
    "learnsets": {"AQUA": {"learnset": [[8, "WATER GUN"]]}, "SQUIRTLE": {"learnset": [[8, "WATER GUN"]]},
                  "MAGIKARP": {"learnset": [[15, "TACKLE"]]}, "WARTORTLE": {"learnset": []},
                  "BLASTOISE": {"learnset": []}, "BLAZE": {"learnset": []}, "BULBASAUR": {"learnset": []},
                  "CHARMANDER": {"learnset": [[9, "EMBER"]]}, "PIDGEY": {"learnset": []}, "SINGER": {"learnset": []},
                  "GYARADOS": {"learnset": []}, "PEBBLE": {"learnset": []}, "NIDORAN(M)": {"learnset": []}},
    "wild_by_map": {
        0x21: {"grass_rate": 25, "grass": [[3, "RATTATA"]] * 4 + [[3, "NIDORAN(M)"]] * 2 + [[4, "PIDGEY"]] * 4},
        0x22: {"grass_rate": 20, "grass": [[4, "PIDGEY"]] * 10},
    },
}
BOSS = [(12, "PEBBLE"), (14, "PEBBLE")]


def _mon(name, level, moves=None):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    types = tuple(dict.fromkeys((row["type1"], row["type2"])))
    return Combatant(name, level, types, hp, st, tuple(moves if moves is not None else row["moves1"]), (8,) * 5, (0,) * 5)


# 1. a member that enables a boss win scores positive
def test_member_that_flips_the_hurt_lead_sim_gains():
    party = [_mon("AQUA", 30)]                       # alone: "no second member" -> not ready
    mv = member_value(Candidate("BLAZE", 28, "wild:34"), party, [("TWO-MON", BOSS)], kb=SYN)
    assert mv.gain >= 1 and mv.value > 0 and "TWO-MON" in mv.contributes


# 2. a useless member scores no gain; dex/cost still priced
WALL = [(50, "AQUA")]   # the hurt-lead sim can never pass this: no member ever "contributes" here


def test_useless_member_has_no_gain():
    party = [_mon("AQUA", 30)]
    mv = member_value(Candidate("SINGER", 2, "wild:34"), party, [("WALL", WALL)], owned_count=5, kb=SYN)
    assert mv.gain == 0 and mv.value == pytest.approx(mv.dex + mv.catcher - mv.cost)
    owned = member_value(Candidate("SINGER", 2, "wild:34"), party, [("WALL", WALL)],
                         owned_species={"SINGER"}, owned_count=5, kb=SYN)
    assert owned.dex == 0


# 3. training cost reduces value; fights_to_reach is hand-checkable
def test_training_cost_reduces_value():
    party = [_mon("AQUA", 30)]
    hi = member_value(Candidate("BLAZE", 28, "wild:34"), party, [("TWO-MON", BOSS)], xp_per_fight=40, kb=SYN)
    lo = member_value(Candidate("BLAZE", 5, "wild:34"), party, [("TWO-MON", BOSS)], xp_per_fight=40, kb=SYN)
    assert lo.fights > hi.fights and lo.value < hi.value
    want = math.ceil(xp_needed("MEDIUM_SLOW", 10, 20) / 40)
    assert fights_to_reach("BLAZE", 10, 20, 40, SYN) == want
    assert fights_to_reach("BLAZE", 10, 20, 40, SYN, trainee=True) == math.ceil(xp_needed("MEDIUM_SLOW", 10, 20) / (40 * TRAINEE_SHARE))
    assert fights_to_reach("BLAZE", 20, 20, 40, SYN) == 0 and fights_to_reach("BLAZE", 10, None, 40, SYN) == 0


# 4. form_at follows the small evolution table
def test_form_at():
    assert form_at("SQUIRTLE", 15) == "SQUIRTLE" and form_at("SQUIRTLE", 16) == "WARTORTLE"
    assert form_at("SQUIRTLE", 36) == "BLASTOISE"
    assert form_at("MAGIKARP", 19) == "MAGIKARP" and form_at("MAGIKARP", 20) == "GYARADOS"
    assert form_at("PIDGEY", 50) == "PIDGEY"


# 5. pokedex_value: gate progress is worth more near a gate; owned is 0
def test_pokedex_value():
    assert pokedex_value("BLAZE", 9, frozenset()) == pytest.approx(DEX_FLOOR_VALUE + DEX_GATE_VALUE / 1)
    assert pokedex_value("BLAZE", 9, frozenset()) > pokedex_value("BLAZE", 4, frozenset())
    assert pokedex_value("BLAZE", 60, frozenset()) == pytest.approx(DEX_FLOOR_VALUE)
    assert pokedex_value("BLAZE", 4, frozenset({"BLAZE"})) == 0
    assert pokedex_value("BLAZE", 8, frozenset()) > pokedex_value("BLAZE", 5, frozenset())


# 6. the catcher role: damaging move required, the band must be empty
def test_catcher_role():
    wild = [(3, "PIDGEY")]
    karp10 = _mon("MAGIKARP", 10, ("SPLASH",))
    assert not qualifies_catcher(karp10, 20, wild, SYN)                  # Splash-only: rejected (Robert's hard rule)
    karp15 = _mon("MAGIKARP", 15, ("SPLASH", "TACKLE"))
    assert qualifies_catcher(karp15, 21, wild, SYN)                      # TACKLE at min roll does not KO the L3 Pidgey
    assert not qualifies_catcher(_mon("SINGER", 14, ("SING",)), 20, wild, SYN)   # status-only: rejected
    party_full = [_mon("AQUA", 20), _mon("PIDGEY", 14, ("TACKLE",))]     # weakest member fills the band
    assert catcher_value(party_full, 20, wild, SYN) == 0
    lone = [_mon("AQUA", 20)]
    assert catcher_value(lone, 20, wild, SYN) == pytest.approx(CATCHER_VALUE)   # nobody weak enough: a catcher has value
    # a low-level candidate is tagged catcher only when nobody already fills the band
    cand = Candidate("NIDORAN(M)", 3, "wild:33")
    mv = member_value(cand, lone, [("TWO-MON", BOSS)], kb=SYN)
    assert mv.candidate.source == "catcher" and mv.catcher == pytest.approx(CATCHER_VALUE)
    mv2 = member_value(cand, party_full, [("TWO-MON", BOSS)], kb=SYN)
    assert mv2.candidate.source != "catcher" and mv2.catcher == 0
    # a KO hit is not safe: a wild mon so frail that even the min roll KOs it proves nothing
    assert not qualifies_catcher(_mon("BLAZE", 14, ("TACKLE",)), 20, [(1, "SINGER")], SYN)


# 7. candidates_for: one Magikarp, each wild species once, starters symmetric
@pytest.mark.parametrize("starter", ["SQUIRTLE", "BULBASAUR", "CHARMANDER"])
def test_candidates_for(starter):
    party = [_mon(starter, 10)]
    cands = candidates_for(party, SYN["wild_by_map"], [0x21, 0x22], None, SYN)
    karps = [c for c in cands if c.source == "magikarp"]
    assert len(karps) == 1 and karps[0].species == "MAGIKARP" and karps[0].level == 5
    by_map = {(c.species, c.source) for c in cands if c.source.startswith("wild:")}
    assert ("NIDORAN(M)", "wild:33") in by_map and ("PIDGEY", "wild:34") in by_map
    evos = [c for c in cands if c.source == "party-evolution"]
    assert [c.species for c in evos] == [starter]
    owned = candidates_for([_mon("AQUA", 30), _mon("MAGIKARP", 13)], {}, [], 13, SYN)
    assert next(c for c in owned if c.source == "magikarp").level == 13


# 8. empty inputs never raise
def test_empty_inputs():
    assert candidates_for([], {}, [], None, SYN) == [Candidate("MAGIKARP", 5, "magikarp")]
    mv = member_value(Candidate("BLAZE", 5, "wild:34"), [], [], kb=SYN)
    assert mv.gain == 0 and mv.value <= mv.dex + mv.catcher
    assert member_value(Candidate("BLAZE", 5, "wild:34"), [_mon("AQUA", 30)], [], kb=None).gain == 0
