"""one_trip: restocking is ONE Mart trip (2026-11-12: after Brock the agent ping-ponged Route 3 <-> Pewter, 353 steps, going back
for 3 Balls, then 1 Potion + 1 Escape Rope, then 1 Potion). Two rules, both on top of economy.plan's list:

* a Mart already visited is not walked to again unless the heal stock is critical (no Potion at all) or the purse grew by
  MIN_TRIP_YEN since: the visit already bought everything affordable (plan.make_list reserves room for the next leg's rope);
* once out on a route, a small top-up (SMALL_TOPUP_UNITS items or fewer, nothing critical) does not turn back; a missing
  Escape Rope before a cave turns back only when the round trip is within TURN_BACK_FRAMES.

Distances reuse the walk-frames helpers (outside_use.walk_frames over the path the caller already searched): no search of its own.
"""
from __future__ import annotations

from pokeagent.explorer.economy import floor, outside_use
from pokeagent.explorer.economy.prices import ESCAPE_ROPE
from pokeagent.goals import bag_contents
from pokeagent.legs import grid as G
from pokeagent.ramworld import read_money

SMALL_TOPUP_UNITS = 2                    # "one or two non-critical items"
TOWN_EDGE_FRAMES = 2 * G.FRAME_WALK * 8  # round trip within ~8 tiles of the Mart: still "in or next to town"
TURN_BACK_FRAMES = 2 * G.FRAME_WALK * 30 # the longest round trip worth turning back for a missing Escape Rope


ROUTE_MAPS = range(0x0C, 0x25)  # Routes 1-25: the overworld between towns (cities and interiors are not "out on a route")


def on_route(map_id: int) -> bool:
    return map_id in ROUTE_MAPS


def units(trip) -> int:
    return sum(q for _, q in trip.items)


def heal_critical(trip, bag: dict) -> bool:
    """No heal item at all, and the trip buys one: the survival logic needs it."""
    return floor.trip_is_floor(trip.items, bag)


def rope_critical(trip, bag: dict) -> bool:
    """The list holds an Escape Rope only when a cave leg is next and the bag has none."""
    return any(i == ESCAPE_ROPE for i, _ in trip.items) and not bag.get(ESCAPE_ROPE, 0)


def round_trip_frames(path_len: int) -> float:
    """Frames there and back over ``path_len`` steps (outside_use.walk_frames; the grass share is its own GRASS_GUESS)."""
    return outside_use.walk_frames(G.FRAME_WALK * path_len, int(path_len * outside_use.GRASS_GUESS), 1, 1)


def usable_marts(st: dict, marts: frozenset, money: int, heal_is_critical: bool) -> frozenset:
    """Drop the Marts already visited unless the heal need is critical or the purse has grown enough to buy a new trip's worth."""
    from pokeagent.explorer.economy.shopping import MIN_TRIP_YEN  # shopping imports this module: late import
    seen = st.get("visited", {})
    if heal_is_critical:
        return marts
    return frozenset(m for m in marts if m not in seen or money >= seen[m] + MIN_TRIP_YEN)


def note_visit(st: dict, mart: int, money_after: int) -> None:
    st.setdefault("visited", {})[mart] = money_after


def allow(ctx, trip, in_mart: bool, path_len: int | None) -> tuple[bool, str]:
    """May the agent start a Mart trip now? ``path_len``: steps to the nearest usable Mart (None when standing in one)."""
    if in_mart or path_len is None or not on_route(ctx.view.m):
        return True, "in town"
    bag, frames = bag_contents(ctx.emu), round_trip_frames(path_len)
    if heal_critical(trip, bag):
        return True, "no heal item"
    if frames <= TOWN_EDGE_FRAMES:
        return True, "next to town"
    if rope_critical(trip, bag) and frames <= TURN_BACK_FRAMES:
        return True, "no Escape Rope before a cave"
    if units(trip) <= SMALL_TOPUP_UNITS or rope_critical(trip, bag):
        return False, f"not turning back for a small top-up ({frames:.0f} frames round trip)"
    return True, "full list"


def essentials_cost(bag: dict, heal_need_potions: int, want_rope: bool, potion_price: int, rope_price: int) -> int:
    """What the Potions and the Escape Rope cost: a ball order leaves room for them so one visit buys the whole list."""
    return heal_need_potions * potion_price + (rope_price if want_rope and not bag.get(ESCAPE_ROPE, 0) else 0)


__all__ = ["allow", "usable_marts", "note_visit", "essentials_cost", "TURN_BACK_FRAMES", "TOWN_EDGE_FRAMES", "SMALL_TOPUP_UNITS"]
