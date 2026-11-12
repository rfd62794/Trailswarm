"""retreat_heal: retreat to the nurse when the next likely fight costs too much HP, earlier when she is close."""
from __future__ import annotations

from dataclasses import replace

from pokeagent.explorer import retreat_risk as rr
from pokeagent.knowledge.party import trainer_mon
from pokeagent.procedures import after_victory_rules as av
from test_after_victory import SYN, _mon

WILD = {"PEBBLEMON": (10, 14, 1.0)}   # a one-species grass: the top level (14) sets the risk


def _lead(frac, level=12):
    return [_mon("AQUAMON", level, frac), _mon("AQUAMON", 12, 1.0)]


def test_floor_rises_as_the_nurse_gets_closer():
    assert rr.floor_for(300) == rr.FLOOR_NEAR and rr.floor_for(5000) == rr.FLOOR_FAR
    assert rr.floor_for(300) > rr.floor_for(1500) > rr.floor_for(2900)


def test_full_party_never_retreats():
    assert not rr.assess(_lead(1.0), WILD, 200, SYN).retreat


def test_unknown_or_far_nurse_never_retreats():
    hurt = [_mon("AQUAMON", 12, 0.1), _mon("AQUAMON", 12, 0.1)]
    assert not rr.assess(hurt, WILD, None, SYN).retreat
    assert not rr.assess(hurt, WILD, rr.MAX_WALK_FRAMES + 1, SYN).retreat


def test_hurt_lead_retreats_near_but_the_same_state_pushes_on_far():
    """A lead the worst wild duel leaves between the two floors: a short walk retreats, a long trek does not."""
    party = [_mon("AQUAMON", 12, 0.5), _mon("AQUAMON", 12, 1.0)]
    foes = rr._worst_wild(WILD, SYN)
    from pokeagent.knowledge.readiness import _chart, duel
    from pokeagent.knowledge.kb import table
    left = duel(party[0], float(party[0].hp), foes[0], float(foes[0].hp), _chart(SYN), table(SYN, "moves"))[0] / rr._max_hp(party[0], SYN)
    assert rr.FLOOR_FAR < left < rr.FLOOR_NEAR, left   # fixture sanity: this is the band where distance decides
    assert rr.assess(party, WILD, 300, SYN).retreat
    assert not rr.assess(party, WILD, rr.FAR_FRAMES, SYN).retreat


def test_low_party_total_always_retreats_when_a_nurse_is_known():
    party = [_mon("AQUAMON", 12, 0.2), _mon("AQUAMON", 12, 0.2)]
    assert rr.assess(party, {}, 3500, SYN).retreat


def test_fainted_lead_with_a_healthy_second_is_judged_on_the_second():
    party = [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)]
    assert not rr.assess(party, WILD, 300, SYN).retreat


# --- after_victory: a close nurse makes "push" need a healthier party ---
BOSS = [[(12, "PEBBLEMON"), (14, "PEBBLEMON")]]


def test_after_victory_heals_instead_of_pushing_at_63_percent_lead_41_percent_party_near_a_center():
    party = [_mon("AQUAMON", 30, 0.63), _mon("AQUAMON", 28, 0.2)]
    d = av.decide(party, BOSS, {}, (900, 0, 58), SYN)
    assert d.action == "heal"


def test_after_victory_still_pushes_when_healthy_or_the_center_is_far():
    healthy = [_mon("AQUAMON", 30, 0.9), _mon("AQUAMON", 28, 0.9)]
    assert av.decide(healthy, BOSS, {}, (900, 0, 58), SYN).action == "push"
    hurt = [_mon("AQUAMON", 30, 0.63), _mon("AQUAMON", 28, 0.2)]
    assert av.decide(hurt, BOSS, {}, (3000, 0, 58), SYN).action == "push"
