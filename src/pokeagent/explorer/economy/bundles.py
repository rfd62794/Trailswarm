"""Bandit seam (not wired): two or three candidate shopping bundles for one Mart visit, so a future bandit decision can pick one."""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer.economy.shopping import shopping_list


@dataclass(frozen=True)
class Bundle:
    name: str
    items: tuple  # ((item_id, qty), ...)


def candidate_bundles(goals: dict, bag: dict, money: int, party, stats, **kw) -> list[Bundle]:
    """lean = the minimum (balls + potion floor), standard = shopping_list as is, stocked = 1.5x potions plus the extras."""
    variants = {"lean": dict(potion_scale=0.0, extras=False), "standard": {}, "stocked": dict(potion_scale=1.5)}
    out: list[Bundle] = []
    for name, extra in variants.items():
        items = tuple(shopping_list(goals, bag, money, party, stats, **{**kw, **extra}))
        if all(b.items != items for b in out):
            out.append(Bundle(name, items))
    return out
