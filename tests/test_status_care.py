"""status_care (pure): the status-byte decode, steps_to_faint, the care decision table, poisoners_on, poison_ahead."""
from __future__ import annotations

from pokeagent.explorer import status_care as sc
from pokeagent.explorer.economy.prices import ANTIDOTE, FULL_HEAL, POTION, SUPER_POTION


def M(slot, hp, mx=40, kinds=frozenset()):
    return sc.MonStatus(slot, hp, mx, frozenset(kinds))


# ---- status_kinds: the (unverified) Gen 1 decode ----
def test_status_kinds_each_bit_and_combos():
    assert sc.status_kinds(0) == frozenset()
    for b in range(1, 8):
        assert sc.status_kinds(b) == frozenset({"sleep"})          # low 3 bits = the sleep counter
    assert sc.status_kinds(0x08) == frozenset({"poison"})
    assert sc.status_kinds(0x10) == frozenset({"burn"})
    assert sc.status_kinds(0x20) == frozenset({"freeze"})
    assert sc.status_kinds(0x40) == frozenset({"paralysis"})
    assert sc.status_kinds(0x0B) == frozenset({"sleep", "poison"})  # counter 3 + the poison bit
    assert sc.status_kinds(0x48) == frozenset({"poison", "paralysis"})
    assert sc.status_kinds(0xFF) == frozenset({"sleep", "poison", "burn", "freeze", "paralysis"})


def test_steps_to_faint():
    assert sc.steps_to_faint(1) == 1 and sc.steps_to_faint(10) == 37 and sc.steps_to_faint(0) == 0
    assert sc.steps_to_faint(2, per_hp=8) == 9


# ---- the decision table ----
def test_no_poisoned_member_is_none():
    assert sc.decide([M(0, 10), M(1, 30)], {}, 50).action == "none"
    assert sc.decide([], {}, 50).action == "none"


def test_poison_close_enough_to_the_nurse_is_none():
    d = sc.decide([M(0, 30, 40, {"poison"})], {}, 20)
    assert d.action == "none" and "poison ok" in d.why   # 117 steps to faint vs 20+8 needed


def test_antidote_is_preferred_and_full_heal_the_fallback():
    party = [M(0, 5, 40, {"poison"})]
    d = sc.decide(party, {ANTIDOTE: 1, FULL_HEAL: 1, POTION: 1}, 100)
    assert (d.action, d.slot, d.item) == ("antidote", 0, ANTIDOTE)
    d = sc.decide(party, {FULL_HEAL: 1}, 100)
    assert (d.action, d.item) == ("antidote", FULL_HEAL)


def test_a_potion_that_buys_enough_steps_and_one_that_does_not():
    party = [M(0, 5, 40, {"poison"})]      # faint in 17; +20 HP -> faint in 97
    d = sc.decide(party, {POTION: 1}, 80)  # need 88: the potion buys it
    assert (d.action, d.slot, d.item) == ("potion", 0, POTION)
    d = sc.decide(party, {POTION: 1}, 120)
    assert d.action == "walk_to_center"    # 97 < 128: the potion cannot cover it
    d = sc.decide(party, {SUPER_POTION: 1}, 120)
    assert d.action == "potion" and d.item == SUPER_POTION   # +50 HP -> faint in 217


def test_walk_and_nothing_available():
    d = sc.decide([M(0, 30, 40), M(1, 5, 40, {"poison"})], {}, 80)
    assert d.action == "walk_to_center" and "member loss" in d.why
    d = sc.decide([M(0, 30, 40), M(1, 5, 40, {"poison"})], {}, None)
    assert d.action == "nothing_available"
    d = sc.decide([M(0, 30, 40), M(1, 5, 40, {"poison"})], {POTION: 1}, None)   # no known heal: a potion only delays it
    assert d.action == "nothing_available"


def test_urgency_wording_blackout_risk_vs_member_loss():
    all_sick = [M(0, 5, 40, {"poison"}), M(1, 8, 30, {"poison"})]
    one_sick = [M(0, 30, 40), M(1, 8, 30, {"poison"})]
    assert "blackout risk" in sc.decide(all_sick, {}, 80).why
    assert "member loss" in sc.decide(one_sick, {}, 80).why
    d = sc.decide(all_sick, {ANTIDOTE: 1}, 80)
    assert d.slot == 0 and "blackout risk" in d.why        # the worst-case member is treated (17 < 29)


def test_burn_paralysis_sleep_freeze_rows_are_none():
    for kinds in ({"burn"}, {"paralysis"}, {"sleep"}, {"freeze"}):
        d = sc.decide([M(0, 5, 40, kinds)], {ANTIDOTE: 1}, None)
        assert d.action == "none" and "no field cure in v1" in d.why


# ---- poisoners_on ----
def _species(name, t1, t2, moves1=()):
    return {"name": name, "type1": t1, "type2": t2, "moves1": list(moves1)}


KB = {
    "species_by_dex": {"1": _species("WEEDLE", "BUG", "POISON", ["TACKLE"]),
                       "2": _species("PIDGEY", "NORMAL", "FLYING", ["TACKLE"]),
                       "3": _species("GASSER", "NORMAL", "NORMAL", ["TACKLE"]),
                       "4": _species("LATER", "NORMAL", "NORMAL", ["TACKLE"])},
    "learnsets": {"WEEDLE": {"learnset": []}, "PIDGEY": {"learnset": []},
                  "GASSER": {"learnset": [[5, "POISON GAS"]]}, "LATER": {"learnset": [[9, "POISON GAS"]]}},
    "moves": {"1": {"name": "TACKLE", "effect": 0}, "2": {"name": "POISON GAS", "effect": 0x42}},
    "wild_by_map": {0x0D: {"grass": [[4, "WEEDLE"]] * 10},
                    0x0E: {"grass": [[5, "GASSER"]] * 10},
                    0x0F: {"grass": [[5, "LATER"]] * 10},
                    0x10: {"grass": [[3, "PIDGEY"]] * 10}},
}


def test_poisoners_on_typed_species_move_species_and_a_clean_map():
    assert sc.poisoners_on(0x0D, kb=KB) == ["WEEDLE"]          # poison-typed: a poisoner whatever it knows
    assert sc.poisoners_on(0x0E, kb=KB) == ["GASSER"]          # knows a poison-effect move at the map's level
    assert sc.poisoners_on(0x0F, kb=KB) == []                  # learns it only above this map's level
    assert sc.poisoners_on(0x10, kb=KB) == []                  # clean
    assert sc.poisoners_on(0x99, kb=KB) == []                  # no table row


def test_poison_ahead_on_fixture_goals_and_maps():
    base = {"potion": True, "left_house": True, "first_pokemon": True, "won_battle": True}
    # unmet[:3] = to_route1 (map 12) / to_viridian (1) / oaks_parcel (item): lookahead maps {12, 1} + stage train map
    # beat_brock -> Route 1 (12) + here_map. A Weedle on Route 1 (12) counts as poison ahead.
    assert sc.poison_ahead(base, 0x0C, KB["wild_by_map"], kb=KB) is False        # Route 1 has no grass row in the fixture
    wild = dict(KB["wild_by_map"]); wild[12] = {"grass": [[3, "WEEDLE"]] * 10}
    assert sc.poison_ahead(base, 0x0C, wild, kb=KB) is True                      # the training map can poison
    assert sc.poison_ahead(base, 0x0D, KB["wild_by_map"], kb=KB) is True         # standing on a Weedle map
    clean = {12: {"grass": [[3, "PIDGEY"]] * 10}, 1: {"grass": [[3, "PIDGEY"]] * 10}}
    assert sc.poison_ahead(base, 0x0C, clean, kb=KB) is False                    # nothing poisonous anywhere ahead
