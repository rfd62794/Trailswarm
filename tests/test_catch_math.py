"""catch_math: the Gen 1 capture formula - the directive's three worked examples, monotonicity,
status bonuses, the ball choice, the status-byte decode."""
from __future__ import annotations

import math

import pytest

from pokeagent.knowledge.catch_math import (BALL_DIV, BALL_RMAX, expected_throws, p_catch, best_ball,
                                            status_kind)

PRICE = {"POKE": 200, "GREAT": 600, "ULTRA": 1200}


# the three worked examples of the directive, computed by hand from the same formula (1e-3)
def test_worked_examples():
    # A: Poke Ball, no status, catch_rate 255, 20/20 HP: f = 85 -> 256*(86/256)/256
    assert p_catch(255, 20, 20, "POKE") == pytest.approx(0.3359, abs=1e-3)
    # B: Great Ball, asleep (s = 25), catch_rate 45, 25/100 HP: f saturates -> (25 + 46) / 201
    assert p_catch(45, 25, 100, "GREAT", "sleep") == pytest.approx(0.3532, abs=1e-3)
    # C: Ultra Ball, no status, catch_rate 45, 35/100 HP: f saturates -> 46 / 151
    assert p_catch(45, 35, 100, "ULTRA") == pytest.approx(0.3046, abs=1e-3)
    # a weakened easy target: f saturates for the Poke Ball too -> certain
    assert p_catch(255, 5, 20, "POKE") == pytest.approx(1.0, abs=1e-3)


def test_master_ball_and_clamping():
    assert p_catch(3, 1, 999, "MASTER") == 1.0
    assert p_catch(3, 1, 999, "MASTER", "sleep") == 1.0
    assert 0.0 <= p_catch(0, 0, 0, "POKE") <= 1.0


def test_monotone_in_catch_rate_and_hp():
    for ball in ("POKE", "GREAT", "ULTRA"):
        assert p_catch(255, 50, 100, ball) > p_catch(45, 50, 100, ball)
        assert p_catch(45, 10, 100, ball) > p_catch(45, 90, 100, ball)


def test_status_ordering():
    base = p_catch(100, 50, 100, "POKE")
    par = p_catch(100, 50, 100, "POKE", "paralyse")
    slp = p_catch(100, 50, 100, "POKE", "sleep")
    assert slp > par > base
    assert p_catch(100, 50, 100, "POKE", "freeze") == pytest.approx(slp)
    assert p_catch(100, 50, 100, "POKE", "burn") == pytest.approx(par)


def test_ultra_vs_great_by_hand():
    # same inputs: the Ultra window (151 outcomes) beats the Great (201), both saturate f -> 46/n
    assert p_catch(45, 35, 100, "ULTRA") == pytest.approx(46 / 151, abs=1e-3)
    assert p_catch(45, 35, 100, "GREAT") == pytest.approx(46 * 256 / 256 / 201, abs=1e-3)
    assert p_catch(45, 35, 100, "ULTRA") > p_catch(45, 35, 100, "GREAT")


def test_best_ball_value_and_empty_bag():
    # a Great Ball is not worth 3x the price: the modest P gain never pays for itself -> POKE
    assert best_ball(45, 100, 100, None, {"POKE": 5, "GREAT": 5}, PRICE)[0] == "POKE"
    # with no Poke Ball in the bag the Great's saturated f beats the Ultra's at half its price -> GREAT
    ball, p = best_ball(45, 5, 100, None, {"POKE": 0, "GREAT": 2, "ULTRA": 1}, PRICE)
    assert ball == "GREAT" and p == pytest.approx(p_catch(45, 5, 100, "GREAT"))
    # it is worth it when the bigger ball is what the bag holds
    assert best_ball(45, 5, 100, None, {"GREAT": 3}, PRICE)[0] == "GREAT"
    assert best_ball(45, 5, 100, None, {}, PRICE) is None
    assert best_ball(45, 5, 100, None, {"POKE": 0}, PRICE) is None
    # the Master Ball is never spent while a lesser ball exists
    assert best_ball(45, 5, 100, None, {"MASTER": 1, "POKE": 1}, PRICE)[0] == "POKE"
    assert best_ball(45, 5, 100, None, {"MASTER": 1}, PRICE) == ("MASTER", 1.0)


def test_status_kind_bits():
    assert status_kind(0x00) is None
    for n in (1, 3, 7):
        assert status_kind(n) == "sleep"      # bits 0-2 are the sleep counter
    assert status_kind(0x08) == "poison"
    assert status_kind(0x10) == "burn"
    assert status_kind(0x20) == "freeze"
    assert status_kind(0x40) == "paralyse"
    assert status_kind(0x80) is None


def test_expected_throws():
    assert expected_throws(0.5) == pytest.approx(2.0)
    assert expected_throws(0) == math.inf and expected_throws(-1) == math.inf
