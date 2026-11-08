"""The Gen 1 capture formula (pokered ``ItemUseBall``) as exact integer counting, plus the ball choice.

One ball throw: R1 uniform on ``0..BALL_RMAX``; a status bonus ``s`` catches outright when ``R1 < s``,
otherwise ``R1 -= s``; the throw fails when ``R1 > catch_rate``; else a second roll ``R2`` on ``0..255``
catches iff ``R2 <= f`` with ``f`` built from the max/current HP. ``p_catch`` counts the integer outcomes
exactly (no floating-point shortcuts) and clamps to ``[0, 1]``.

UNVERIFIED constants: the ball ids, ball random ranges, HP divisors, status bonuses, fallback prices and
the status-byte bit layout are all from memory of the pokered disassembly (each marked ``# unverified``);
the controller verifies them against the disassembly and the ROM. Pure module: no emulator, no RAM.
"""
from __future__ import annotations

import math

BALLS = {"MASTER": 1, "ULTRA": 2, "GREAT": 3, "POKE": 4}      # unverified: from memory of pokered ItemUseBall (only POKE = 0x04 confirmed in-repo)
BALL_RMAX = {"POKE": 255, "GREAT": 200, "ULTRA": 150}        # unverified: from memory of pokered ItemUseBall
BALL_DIV = {"POKE": 12, "GREAT": 8, "ULTRA": 12}             # unverified: from memory of pokered ItemUseBall
STATUS_BONUS = {"sleep": 25, "freeze": 25, "poison": 12, "burn": 12, "paralyse": 12}   # unverified: from memory of pokered ItemUseBall
FALLBACK_PRICE = {"POKE": 200, "GREAT": 600, "ULTRA": 1200}  # unverified: from memory of pokered ItemUseBall

# the battle status byte; unverified: from memory of pokered (this ONE helper owns the decode so a fix lands in one place)
SLP_MASK, PSN_BIT, BRN_BIT, FRZ_BIT, PAR_BIT = 0x07, 0x08, 0x10, 0x20, 0x40

_BALL_ORDER = ("POKE", "GREAT", "ULTRA", "MASTER")           # cheapest first: a P/price tie keeps the cheaper ball


def status_kind(byte: int) -> str | None:
    """Battle status byte -> "sleep" | "poison" | "burn" | "freeze" | "paralyse" | None.
    Sleep is the counter in bits 0-2 (nonzero); the rest are single bits."""
    if byte & SLP_MASK:
        return "sleep"
    if byte & FRZ_BIT:
        return "freeze"
    if byte & BRN_BIT:
        return "burn"
    if byte & PSN_BIT:
        return "poison"
    if byte & PAR_BIT:
        return "paralyse"
    return None


def p_catch(catch_rate: int, hp: int, hp_max: int, ball: str = "POKE", status: str | None = None) -> float:
    """P(one throw catches): Master Ball always; else the exact count of R1 outcomes that catch.
    ``status`` is a status_kind string (the bonus that applies); ``hp``/``hp_max`` the foe's HP."""
    if ball == "MASTER":
        return 1.0
    rmax = BALL_RMAX.get(ball, BALL_RMAX["POKE"])
    div = BALL_DIV.get(ball, BALL_DIV["POKE"])
    s = STATUS_BONUS.get(status or "", 0)
    n = rmax + 1                                                  # R1 uniform on 0..rmax inclusive
    caught = min(s, n)                                            # R1 < s catches outright
    passed = max(0, min(rmax, s + catch_rate) - s + 1)            # s <= R1 and R1 - s <= catch_rate
    f = min(255, hp_max * 255 // div // max(1, hp // 4))
    return max(0.0, min(1.0, (caught + passed * (f + 1) / 256) / n))


def expected_throws(p: float) -> float:
    """Throws one catch is expected to need: 1 / p (inf when p <= 0)."""
    return 1 / p if p > 0 else math.inf


def best_ball(catch_rate: int, hp: int, hp_max: int, status: str | None,
              bag: dict[str, int], price: dict[str, int]) -> tuple[str, float] | None:
    """The (ball, p) in ``bag`` with the highest P(catch) / price. The Master Ball is never spent
    unless it is the only ball in the bag. ``bag``/``price`` are keyed by ball name; a missing price
    falls back to FALLBACK_PRICE. None when the bag holds no balls."""
    have = [b for b in _BALL_ORDER if (bag or {}).get(b, 0) > 0]
    if "MASTER" in have and len(have) > 1:
        have.remove("MASTER")                                   # a Master Ball is kept unless it is the only one
    best: tuple[float, str, float] | None = None
    for b in have:
        p = p_catch(catch_rate, hp, hp_max, b, status)
        cost = int((price or {}).get(b) or FALLBACK_PRICE.get(b, FALLBACK_PRICE["POKE"]))
        ratio = p / max(cost, 1)
        if best is None or ratio > best[0]:
            best = (ratio, b, p)
    return (best[1], best[2]) if best else None
