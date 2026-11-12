"""The Magikarp money reserve and the circle-back rule. Pure functions and constants: no emulator, no ctx.

From Pewter on, the salesman's 500 yen (plus one cheap item of margin) is untouchable:
``budget.reserve`` reads ``magikarp_floor`` on every purchase decision, so the money is still there at
the Mt Moon Pokemon Center (map 0x44). Arriving poor no longer settles the goal - it defers it
(``explorer.magikarp_deferral``), and ``should_circle_back`` says when the trip back is worth it.
"""
from __future__ import annotations

from pokeagent.magikarp import MAGIKARP_PRICE, MT_MOON_CENTER

MAGIKARP_RESERVE_MARGIN = 100   # yen kept above MAGIKARP_PRICE: one Antidote of slack (the cheapest list item)
CIRCLE_BACK_MAX_PATH = 80       # a trip to 0x44 longer than this many path steps is not worth it
CIRCLE_BACK_STEP_CAP = 1500     # steps with the goal deferred before it settles as skipped
WEST_OF_MT_MOON = frozenset({0x02, 0x0E, 0x0F})   # Pewter, Route 3, Route 4


def reserve_active(st: dict, seen: set) -> bool:
    """Pewter reached (0x02 in seen), no Magikarp owned or ever owned, goal not skipped, Mt Moon 1F (0x3B) not seen."""
    return (0x02 in seen
            and not st.get("had_magikarp")
            and not st.get("buy_skipped")
            and 0x3B not in seen)


def magikarp_floor(st: dict, seen: set) -> int:
    """MAGIKARP_PRICE + MAGIKARP_RESERVE_MARGIN while reserve_active, else 0."""
    return MAGIKARP_PRICE + MAGIKARP_RESERVE_MARGIN if reserve_active(st, seen) else 0


def should_circle_back(money: int, party_count: int, map_id: int, path_len: int | None) -> bool:
    """The buy attempt is worth resuming: money restored to price + margin, a free party slot, still on
    the Pewter side of Mt Moon (or inside the center itself, e.g. back to heal), and a learned route to
    0x44 within CIRCLE_BACK_MAX_PATH. ``path_len`` None = the learned graph knows no way there."""
    return (money >= MAGIKARP_PRICE + MAGIKARP_RESERVE_MARGIN
            and party_count < 6
            and map_id in WEST_OF_MT_MOON | {MT_MOON_CENTER}
            and path_len is not None
            and path_len <= CIRCLE_BACK_MAX_PATH)
