"""status_care shopping: the Antidote joins the list only while poison is ahead and the Mart stocks it."""
from __future__ import annotations

from pokeagent.explorer.economy import heal_items, hp_stats, shopping
from pokeagent.explorer.economy.prices import ANTIDOTE, FULL_HEAL, POTION, SUPER_POTION, price

PARTY = [[1, 10, 0, 30, 30]]
QUIET = hp_stats.HpStats(overall=[10, 30])    # potion floor 1 = 20 HP


def lst(money, bag=None, **kw):
    return shopping.shopping_list(kw.pop("goals", {}), bag or {}, money, PARTY, QUIET,
                                  needs_balls=kw.pop("needs_balls", False), cave=kw.pop("cave", False), **kw)


def test_antidote_joins_the_list_when_poison_is_ahead_and_none_carried():
    assert (ANTIDOTE, 1) in lst(20000, poison_ahead=True)
    assert dict(lst(20000, poison_ahead=True))[ANTIDOTE] == 1


def test_no_antidote_when_one_is_carried_or_the_mart_lacks_it():
    assert ANTIDOTE not in dict(lst(20000, {ANTIDOTE: 1}, poison_ahead=True))
    assert ANTIDOTE not in dict(lst(20000, {FULL_HEAL: 1}, poison_ahead=True))          # a Full Heal counts as the cure
    stock = {67: [POTION, SUPER_POTION]}
    out = lst(20000, poison_ahead=True, mart=67, stock=lambda i, m: i in stock[m])
    assert ANTIDOTE not in dict(out) and (POTION, 1) in out                            # the potion still buys
    out = lst(20000, poison_ahead=True, mart=67, stock=lambda i, m: True)
    assert (ANTIDOTE, 1) in out


def test_no_antidote_without_poison_ahead_or_when_the_reserve_blocks_it():
    assert ANTIDOTE not in dict(lst(20000, poison_ahead=False))
    assert ANTIDOTE not in dict(lst(20000))                       # default: computed - no ROM tables in the worktree -> False
    assert ANTIDOTE not in dict(lst(500, poison_ahead=True))      # reserve ~300+125 leaves 75: unaffordable


def test_potion_maths_and_trip_gate_are_unchanged():
    kw = dict(poison_ahead=False)
    assert lst(20000, **kw) == [(POTION, 1)]
    assert lst(20000, {POTION: 1}, **kw) == []
    assert heal_items.bag_hp({ANTIDOTE: 2, FULL_HEAL: 1}) == 0    # cures restore no HP
    assert heal_items.cure_count({ANTIDOTE: 2, FULL_HEAL: 1, POTION: 3}) == 3
    assert shopping.cost([(ANTIDOTE, 1)]) == price(ANTIDOTE) < shopping.MIN_TRIP_YEN
    assert not shopping.trip_worth([(ANTIDOTE, 1)], {})            # a lone Antidote never justifies the walk
    assert price(ANTIDOTE) == 100 and price(FULL_HEAL) == 600      # fallbacks (no ROM tables here)
