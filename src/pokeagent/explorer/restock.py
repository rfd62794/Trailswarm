"""restock: when to buy Poke Balls and where (pure rules; the walking and the purchase are behaviours/restock.py).

Rule: balls < BALL_MIN, money >= BALL_BUY balls + MONEY_RESERVE, a Mart on the route within MAX_PATH steps, and the per-run
caps (MAX_TRIES purchases attempted, MAX_TRIP_STEPS presses per trip) not yet spent. Every Mart has the same shape
(ROM-verified for Viridian 42, Pewter 56, Cerulean 67; learned maps agree): the door is (3,7), the clerk at (0,5) behind the
counter, and the shop spot is (2,5) facing LEFT.
"""
from __future__ import annotations

from pokeagent.explorer.kb import ROM_KB

BALL_ID, BALL_MIN, BALL_BUY, MONEY_RESERVE = 0x04, 5, 10, 300
MAX_TRIES, MAX_TRIP_STEPS, MAX_PATH, RECHECK_EVERY = 3, 220, 60, 25
MART_MAPS = frozenset({42, 56, 67, 91, 150, 152, 172, 180})  # Viridian Pewter Cerulean Vermilion Lavender Fuchsia Cinnabar Saffron
VIRIDIAN_MART = 42  # the clerk only sells after the parcel is delivered
SHOP_SPOT, SHOP_FACING = (2, 5), "LEFT"


def ball_price() -> int:
    return int(((ROM_KB or {}).get("items", {}).get(str(BALL_ID), {}) or {}).get("price") or 200)


def buy_quantity(money: int) -> int:
    return max(0, min(BALL_BUY, (money - MONEY_RESERVE) // ball_price()))


def ball_buy_wanted(balls: int, money: int, tries: int = 0) -> bool:
    """The money/stock part of the rule (whether a Mart is near is the behaviour's path check)."""
    return balls < BALL_MIN and tries < MAX_TRIES and money >= ball_price() * BALL_BUY + MONEY_RESERVE


def candidate_marts(goals: dict, failed=()) -> frozenset:
    return frozenset(m for m in MART_MAPS if m not in failed and (m != VIRIDIAN_MART or goals.get("deliver_parcel")))
