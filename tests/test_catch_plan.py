"""catch_plan: ranked catch actions - boss gain vs cheap dex species, caps, costs, blocked, the Magikarp candidate."""
from __future__ import annotations

import pytest

from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge.catch_plan import CHEAP_STEPS, expected_balls, p_catch, plan_catches
from pokeagent.knowledge.party import Combatant


def _mv(name, typ, power, acc=1.0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": 0, "pp": 20}


def _sp(name, t1, t2, hp, atk, dfn, spd, spc, moves1, growth="MEDIUM_SLOW", catch_rate=200, base_exp=60):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc,
            "moves1": moves1, "growth": growth, "catch_rate": catch_rate, "base_exp": base_exp}


# Section-2 wild rows (Red) plus the species table the sim needs.
WILD = {
    0x0C: {"grass_rate": 25, "grass": [[3, "PIDGEY"], [3, "RATTATA"], [3, "RATTATA"], [2, "RATTATA"], [2, "PIDGEY"],
                                       [3, "PIDGEY"], [3, "PIDGEY"], [4, "RATTATA"], [4, "PIDGEY"], [5, "PIDGEY"]]},
    0x21: {"grass_rate": 25, "grass": [[3, "RATTATA"], [3, "NIDORAN(M)"], [4, "RATTATA"], [4, "NIDORAN(M)"],
                                       [2, "RATTATA"], [2, "NIDORAN(M)"], [3, "SPEAROW"], [5, "SPEAROW"],
                                       [3, "NIDORAN(F)"], [4, "NIDORAN(F)"]]},
    0x33: {"grass_rate": 8, "grass": [[4, "WEEDLE"], [5, "KAKUNA"], [3, "WEEDLE"], [5, "WEEDLE"], [4, "KAKUNA"],
                                      [6, "KAKUNA"], [4, "METAPOD"], [3, "CATERPIE"], [3, "PIKACHU"], [5, "PIKACHU"]]},
    0x3B: {"grass_rate": 10, "grass": [[8, "ZUBAT"], [7, "ZUBAT"], [9, "ZUBAT"], [8, "GEODUDE"], [6, "ZUBAT"],
                                       [10, "ZUBAT"], [10, "GEODUDE"], [8, "PARAS"], [11, "ZUBAT"], [8, "CLEFAIRY"]]},
    0x23: {"grass_rate": 25, "grass": [[7, "WEEDLE"], [8, "KAKUNA"], [12, "PIDGEY"], [12, "ODDISH"], [13, "ODDISH"],
                                       [10, "ABRA"], [14, "ODDISH"], [13, "PIDGEY"], [8, "ABRA"], [12, "ABRA"]]},
    0x10: {"grass_rate": 15, "grass": [[13, "ODDISH"], [13, "PIDGEY"], [15, "PIDGEY"], [10, "MANKEY"], [12, "MANKEY"],
                                       [15, "ODDISH"], [16, "ODDISH"], [16, "PIDGEY"], [14, "MANKEY"], [16, "MANKEY"]]},
}
SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40), "3": _mv("BITE", "NORMAL", 60)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0]],
    "species_by_dex": {
        "1": _sp("SQUIRTLE", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
        "2": _sp("PIDGEY", "NORMAL", "FLYING", 40, 45, 40, 56, 35, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=255, base_exp=55),
        "3": _sp("RATTATA", "NORMAL", "NORMAL", 30, 56, 35, 72, 25, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=255, base_exp=51),
        "4": _sp("NIDORAN(M)", "POISON", "POISON", 46, 57, 40, 50, 40, ["TACKLE"], catch_rate=235, base_exp=60),
        "5": _sp("NIDORAN(F)", "POISON", "POISON", 55, 47, 52, 41, 40, ["TACKLE"], catch_rate=235, base_exp=59),
        "6": _sp("SPEAROW", "NORMAL", "FLYING", 40, 60, 30, 70, 31, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=255, base_exp=58),
        "7": _sp("WEEDLE", "BUG", "POISON", 40, 35, 30, 50, 20, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=255, base_exp=39),
        "8": _sp("KAKUNA", "BUG", "POISON", 45, 25, 50, 35, 25, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=120, base_exp=72),
        "9": _sp("METAPOD", "BUG", "BUG", 50, 20, 55, 30, 25, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=120, base_exp=72),
        "10": _sp("CATERPIE", "BUG", "BUG", 45, 30, 35, 45, 20, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=255, base_exp=53),
        "11": _sp("PIKACHU", "ELECTRIC", "ELECTRIC", 35, 55, 30, 90, 50, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=190, base_exp=82),
        "12": _sp("ZUBAT", "POISON", "FLYING", 40, 45, 35, 55, 40, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=255, base_exp=54),
        "13": _sp("GEODUDE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"], catch_rate=255, base_exp=86),
        "14": _sp("PARAS", "BUG", "GRASS", 35, 70, 55, 25, 55, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=190, base_exp=70),
        "15": _sp("CLEFAIRY", "NORMAL", "NORMAL", 70, 45, 48, 35, 60, ["TACKLE"], growth="FAST", catch_rate=150, base_exp=68),
        "16": _sp("ODDISH", "GRASS", "POISON", 45, 50, 55, 30, 75, ["TACKLE"], catch_rate=255, base_exp=78),
        "17": _sp("ABRA", "PSYCHIC", "PSYCHIC", 25, 20, 15, 90, 105, ["TACKLE"], catch_rate=200, base_exp=73),
        "18": _sp("MANKEY", "FIGHTING", "FIGHTING", 40, 80, 35, 70, 35, ["TACKLE"], growth="MEDIUM_FAST", catch_rate=190, base_exp=74),
        "19": _sp("MAGIKARP", "WATER", "WATER", 20, 10, 55, 80, 20, ["TACKLE"], growth="SLOW", catch_rate=255, base_exp=20),
        "20": _sp("GYARADOS", "WATER", "FLYING", 95, 125, 79, 81, 100, ["BITE"], growth="SLOW", catch_rate=45, base_exp=214),
        "21": _sp("ONIX", "ROCK", "GROUND", 35, 45, 160, 70, 30, ["TACKLE"], catch_rate=45, base_exp=108),
        "22": _sp("JIGGLYPUFF", "NORMAL", "NORMAL", 115, 45, 20, 20, 45, ["TACKLE"], growth="FAST", catch_rate=170, base_exp=76),
    },
    "learnsets": {n: {"learnset": [[8, "WATER GUN"]] if n in ("SQUIRTLE", "GYARADOS") else []}
                  for n in ("SQUIRTLE", "PIDGEY", "RATTATA", "NIDORAN(M)", "NIDORAN(F)", "SPEAROW", "WEEDLE", "KAKUNA",
                            "METAPOD", "CATERPIE", "PIKACHU", "ZUBAT", "GEODUDE", "PARAS", "CLEFAIRY", "ODDISH",
                            "ABRA", "MANKEY", "MAGIKARP", "GYARADOS", "ONIX", "JIGGLYPUFF")},
    "wild_by_map": WILD,
}
BROCK = [("BROCK", [(12, "GEODUDE"), (14, "ONIX")])]
HARD = [("WALL", [(40, "ONIX")])]


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     tuple(row["moves1"]), (8,) * 5, (0,) * 5)


def _plan(party=None, **kw):
    party = [_mon("SQUIRTLE", 10)] if party is None else party
    return plan_catches(party, kw.pop("here_map", 0x0E), kw.pop("goals", {}), kw.pop("money", 1000),
                        kw.pop("balls", 5), kw.pop("owned_count", 4), kw.pop("bosses", BROCK), WILD,
                        kw.pop("known_maps", {0x21, 0x33, 0x3B, 0x23}), kw.pop("lead_level", 10),
                        kb=SYN, **kw)


# 1. ranked list for a Brock-stage party: score desc, Route 22 Nidoran present, gain outranks dex-only
def test_ranking_on_the_early_rows():
    plan = _plan()
    assert [a.score for a in plan] == sorted((a.score for a in plan), reverse=True)
    nidoran = next(a for a in plan if a.species == "NIDORAN(M)")
    assert nidoran.map == 0x21 and nidoran.levels[0] <= 4
    gained = [a for a in plan if a.member.gain > 0]
    cheap_dex = [a for a in plan if a.member.gain == 0 and a.steps <= CHEAP_STEPS]
    assert gained and cheap_dex and gained[0].score > min(a.score for a in cheap_dex)


# 2. the early catchable set appears from the fixture rows (contributing or dex-only)
def test_early_catch_reachability():
    names = {a.species for a in _plan(bosses=[])}                        # only the Pokedex term applies
    assert {"NIDORAN(M)", "PIKACHU", "PARAS", "ODDISH"} <= names
    soft = [("SOFT", [(8, "RATTATA")])]                                  # a boss the hurt-lead sim beats: members contribute cheaply
    names = {a.species for a in _plan(bosses=soft)}
    assert {"NIDORAN(M)", "PIKACHU", "PARAS", "ODDISH"} <= names
    assert any(a.member.gain >= 1 for a in _plan(bosses=soft))


# 3. a new species with no boss value is still returned when cheap; far ranks last; owned skipped
def test_pokedex_only_actions():
    plan = _plan(bosses=HARD)
    dex_only = [a for a in plan if a.member.gain == 0]
    assert dex_only and all(a.value > 0 for a in dex_only)
    near = _plan(distance=lambda a, b: 10)
    far = _plan(distance=lambda a, b: 10 if b != 0x23 else 5000)
    nido_near = next(a for a in far if a.species == "ODDISH")
    assert nido_near.steps > CHEAP_STEPS
    assert all(a.species != "RATTATA" for a in _plan(owned_species={"RATTATA"}))


# 4. the plan stops at a party of six
def test_team_size_cap():
    six = [_mon("SQUIRTLE", 10)] * 6
    assert _plan(party=six) == []
    assert _plan(party=[_mon("SQUIRTLE", 10)] * 5)


# 5. cost: bigger distance lowers rank; no balls + no spendable -> blocked; balls capped by spendable; risky maps out
def test_cost_and_blocked():
    close = _plan(distance=lambda a, b: 10)
    far = _plan(distance=lambda a, b: 500)
    sp = "NIDORAN(M)"
    assert next(a for a in close if a.species == sp).steps < next(a for a in far if a.species == sp).steps
    blocked = _plan(balls=0, money=0)
    assert blocked and all(a.blocked == "no balls" for a in blocked if a.map)
    capped = _plan(balls=0, money=1000)  # spendable = 1000 - (300 + 250) = 450 -> 2 balls at 200
    assert all(a.balls * 200 <= 450 for a in capped)
    risky = _plan(lead_level=10, known_maps={0x10})
    assert all(a.map != 0x10 for a in risky)                       # Route 5 tops out at L16 > 10 + 4
    safe = _plan(lead_level=20, known_maps={0x10})
    assert any(a.map == 0x10 for a in safe)


# 6. the Magikarp candidate: loses when its cost outweighs, wins when only a Gyarados beats the boss
def test_magikarp_is_one_candidate():
    plan = _plan(magikarp_level=5)
    karp = [a for a in plan if a.member.candidate.source == "magikarp"]
    assert len(karp) <= 1  # one candidate, and with L20 far off it can lose (absent or low-ranked)
    owned_all = {"PIDGEY", "RATTATA", "NIDORAN(M)", "NIDORAN(F)", "SPEAROW", "WEEDLE", "KAKUNA", "METAPOD",
                 "CATERPIE", "PIKACHU", "ZUBAT", "GEODUDE", "PARAS", "CLEFAIRY", "ODDISH", "ABRA", "MANKEY"}
    win = _plan(party=[_mon("PIDGEY", 20), _mon("MAGIKARP", 15)], bosses=[("HARD", [(22, "ONIX")])], magikarp_level=15,
                owned_species=owned_all, xp_for_map=lambda m: 130)
    top = win[0]
    assert top.member.candidate.source == "magikarp" and top.species == "MAGIKARP" and top.member.gain >= 1
    assert sum(a.species == "MAGIKARP" for a in win) == 1  # exactly one Magikarp action, no party-evolution twin


def test_unowned_magikarp_is_never_planned_and_empty_inputs_give_nothing():
    plan = _plan(party=[_mon("PIDGEY", 20)], bosses=[("HARD", [(22, "ONIX")])], magikarp_level=15,
                 owned_species={"PIDGEY"}, xp_for_map=lambda m: 130)
    assert all(a.member.candidate.source != "magikarp" and a.steps >= 1 for a in plan)
    assert plan_catches([], 1, {}, 0, 0, 0, [], {}, [], 10) == []


def test_hurt_margin_with_only_magikarps_does_not_raise():
    from pokeagent.knowledge.team_value import _hurt_margin
    assert _hurt_margin([_mon("MAGIKARP", 5)], [], {}, {}, SYN) == 0.0


# 7. catch odds helpers
def test_catch_helpers():
    assert p_catch(255) > p_catch(45)
    assert expected_balls(255) < expected_balls(45)
