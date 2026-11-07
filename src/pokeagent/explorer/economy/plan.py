"""plan: what one Mart visit would do right now (sell the whitelisted Nuggets, then buy the shopping list). Reads the live game."""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer import party_log
from pokeagent.explorer.economy import hp_stats, shopping
from pokeagent.explorer.economy.prices import NUGGET, SELL_WHITELIST, sell_price
from pokeagent.goals import bag_contents
from pokeagent.ramworld import read_money

STATS_REFRESH = 400     # steps a read of battles.jsonl is reused


@dataclass(frozen=True)
class TripPlan:
    sell: tuple    # item ids to sell, one entry per unit (whitelist only)
    items: tuple   # ((item_id, qty), ...)


def battle_stats(ctx):
    st = ctx.restock
    if "stats" not in st or ctx.step - st.get("stats_step", -10**9) >= STATS_REFRESH:
        st["stats"], st["stats_step"] = hp_stats.load_hp_loss(st.get("stats_path", "runs/battles.jsonl")), ctx.step
    return st["stats"]


def party_rows(ctx) -> list:
    try:
        return party_log.rows(party_log.snapshot(ctx.emu))
    except Exception:
        return []


def make_list(ctx, bag: dict, money: int, **kw) -> list:
    return shopping.shopping_list(ctx.goals(), bag, money, party_rows(ctx), battle_stats(ctx), map_id=ctx.view.m, **kw)


def trip_plan(ctx) -> TripPlan | None:
    """None when no visit is worth it. The sale counts toward the budget, so a Nugget alone can fund the shopping."""
    bag, money = bag_contents(ctx.emu), read_money(ctx.emu)
    sells = tuple(i for i in SELL_WHITELIST for _ in range(min(bag.get(i, 0), 3)))
    items = make_list(ctx, bag, money + sum(sell_price(i) for i in sells))
    if sells or shopping.trip_worth(items):
        return TripPlan(sells, tuple(items))
    return None


__all__ = ["TripPlan", "trip_plan", "make_list", "NUGGET"]
