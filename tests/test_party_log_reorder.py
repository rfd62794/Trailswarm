"""A party re-order is not progress: members match by identity (OT id + DVs), not by slot."""
from __future__ import annotations

from pokeagent.explorer.party_log import diff

MOVES = (33, 0, 0, 0)


def mon(species, level, exp, ident):
    return (species, level, exp, 10, 20, MOVES, ident)


A, B, C, D = (1, 11), (1, 22), (1, 33), (1, 44)


def test_reorder_records_nothing():
    before = [mon(165, 4, 100, A), mon(112, 4, 90, B), mon(176, 10, 900, C), mon(36, 4, 80, D)]
    after = [before[2], before[1], before[0], before[3]]
    d = diff(before, after)
    assert d["level_ups"] == [] and d["evolved"] == [] and d["moves_learned"] == []
    assert d["exp_gained"] == [0, 0, 0, 0]


def test_levelup_after_reorder_still_logged():
    before = [mon(165, 4, 100, A), mon(176, 10, 900, C)]
    after = [mon(176, 11, 950, C), mon(165, 4, 100, A)]
    d = diff(before, after)
    assert d["level_ups"] == [{"slot": 0, "species": 176, "from": 10, "to": 11}]
    assert d["evolved"] == [] and d["exp_gained"] == [50, 0]


def test_evolution_same_member_logged():
    d = diff([mon(165, 15, 500, A)], [mon(166, 16, 600, A)])
    assert d["evolved"] == [{"slot": 0, "from": 165, "to": 166}]
    assert d["level_ups"] == [{"slot": 0, "species": 166, "from": 15, "to": 16}]


def test_new_catch_has_no_before():
    d = diff([mon(165, 4, 100, A)], [mon(165, 4, 100, A), mon(19, 3, 50, B)])
    assert d["exp_gained"] == [0, 0] and d["level_ups"] == [] and d["evolved"] == []
