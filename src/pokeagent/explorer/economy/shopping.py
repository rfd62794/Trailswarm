"""shopping_list: what to buy in one Mart visit. Priority: balls the catch need-list requires > potions up to ``floor.potion_floor``
(1-3 Potion-equivalents from the segment's expected HP loss; a Super Potion counts 2.5) > an Escape Rope before a cave. Never more than ``budget.spendable`` pays for.
Antidote / Parlyz Heal are skipped: there is no per-area status data in the battle records yet."""
from __future__ import annotations


from pokeagent.explorer.economy import budget, floor, heal_items
from pokeagent.explorer.economy.prices import ESCAPE_ROPE, POKE_BALL, POTION, price, stocked

BALL_MIN, BALL_BUY = 5, 10
MIN_TRIP_YEN = 600     # a Mart trip for less than this is not worth the walk
CAVE_GOALS = frozenset({"to_mt_moon", "mt_moon_b1f", "mt_moon_b2f", "to_rock_tunnel", "rock_tunnel_b1f"})
CAVE_LOOKAHEAD = 4     # unmet goals ahead that count as "a cave segment is next"


def ball_need(goals: dict) -> bool:
    from pokeagent.explorer.catch_list import upcoming_needs
    return any(n in ("dex10", "cut", "flash", "surf", "strength") for n in upcoming_needs(goals))


def cave_ahead(goals: dict) -> bool:
    from pokeagent.campaign import load_campaign
    ahead = [g["id"] for g in load_campaign() if not goals.get(g["id"])][:CAVE_LOOKAHEAD]
    return any(g in CAVE_GOALS for g in ahead)


def shopping_list(goals: dict, bag: dict, money: int, party, stats, *, map_id: int | None = None, needs_balls: bool | None = None,
                  cave: bool | None = None, potion_scale: float = 1.0, extras: bool = True, ref_money: int = 0, mart: int | None = None,
                  stock=None) -> list[tuple[int, int]]:
    """``[(item_id, qty)]`` in buy order; ``needs_balls`` / ``cave`` override the campaign lookups (tests, bundles). ``mart`` = the
    Mart being shopped in: the heal item is then the cheapest one it stocks (``stock(item, mart)``); without it, Potions."""
    left = budget.spendable(goals, money, ref_money)
    balls, rope = bag.get(POKE_BALL, 0), bag.get(ESCAPE_ROPE, 0)
    target = floor.potion_floor(stats, party, map_id, potion_scale)
    want_balls = ball_need(goals) if needs_balls is None else needs_balls
    want_rope = extras and (cave_ahead(goals) if cave is None else cave)
    heal_need = max(0, floor.floor_hp(target) - heal_items.bag_hp(bag))   # Potions and Super Potions count together, in HP
    out: dict[int, int] = {}

    def add(item: int, qty: int) -> int:
        unit = price(item)
        n = min(qty, left // unit) if unit and qty > 0 else 0
        if n > 0:
            out[item] = out.get(item, 0) + n
        return n * unit

    left -= add(POKE_BALL, BALL_BUY if want_balls and balls < BALL_MIN else 0)
    if heal_need:
        if mart is None:   # planning, Mart not known yet: Potions; the visit itself re-sizes for the Mart's stock
            left -= add(POTION, -(-heal_need // heal_items.POTION_HP))
        else:
            sells = stock or stocked
            pick = heal_items.buy_choice(heal_need, lambda i: sells(i, mart), left)
            if pick:
                left -= add(*pick)
    add(ESCAPE_ROPE, 1 if want_rope and not rope else 0)
    return list(out.items())


def cost(items: list[tuple[int, int]]) -> int:
    return sum(price(i) * q for i, q in items)


def trip_worth(items: list[tuple[int, int]], bag: dict | None = None) -> bool:
    return cost(items) >= MIN_TRIP_YEN or floor.trip_is_floor(items, bag or {})
