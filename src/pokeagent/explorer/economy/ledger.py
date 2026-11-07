"""Ledger: the run's money books. Income, spend and blackout losses go to meta.json as ``econ_summary``; the Pokecenters visited
(which move the blackout respawn point) and the field-potion cache live here too. Best effort: never ends a run."""
from __future__ import annotations

from dataclasses import dataclass, field

from pokeagent.ramworld import read_money

LOG_KEEP = 40


@dataclass
class Ledger:
    income: int = 0
    spend: int = 0
    other_spend: int = 0
    blackout_loss: int = 0
    last_money: int | None = None
    purchases: list = field(default_factory=list)   # {step, map, item, qty, cost, money_before, money_after}
    sales: list = field(default_factory=list)
    visited_centers: set = field(default_factory=set)
    field_check_at: int = 0                          # outside_use: step before which the cached decision stands
    field_decision: bool = False
    topup_map: int | None = None                     # map a started potion sequence began on

    def tick(self, ctx) -> None:
        """Every step outside fights: unexplained money changes, and the Pokecenters we have stood in."""
        if ctx.view is not None and ctx.view.m in _centers():
            self.visited_centers.add(ctx.view.m)
        now = read_money(ctx.emu)
        if self.last_money is not None and now != self.last_money:
            if now > self.last_money:
                self.income += now - self.last_money
            else:
                self.other_spend += self.last_money - now
        self.last_money = now

    def battle(self, before: int, after: int, won: bool, fled: bool) -> None:
        """A fight changed the money: up = prize money, down = the blackout that halves it."""
        if after > before:
            self.income += after - before
        elif after < before and not won and not fled:
            self.blackout_loss += before - after
        elif after < before:
            self.other_spend += before - after
        self.last_money = after

    def purchase(self, ctx, item: int, qty: int, money_before: int, money_after: int) -> None:
        self.spend += max(0, money_before - money_after)
        self.purchases.append({"step": ctx.step, "map": ctx.view.m, "item": item, "qty": qty,
                               "cost": money_before - money_after, "money_before": money_before, "money_after": money_after})
        del self.purchases[:-LOG_KEEP]
        self.last_money = money_after

    def sale(self, ctx, item: int, money_before: int, money_after: int) -> None:
        self.income += max(0, money_after - money_before)
        self.sales.append({"step": ctx.step, "map": ctx.view.m, "item": item, "gained": money_after - money_before,
                           "money_before": money_before, "money_after": money_after})
        del self.sales[:-LOG_KEEP]
        self.last_money = money_after

    def summary(self) -> dict:
        return {"income": self.income, "spend": self.spend, "other_spend": self.other_spend, "blackout_loss": self.blackout_loss,
                "net": self.income - self.spend - self.other_spend - self.blackout_loss,
                "purchases": self.purchases, "sales": self.sales}


def _centers() -> frozenset:
    from pokeagent.explorer.world import POKECENTER_MAPS
    return POKECENTER_MAPS


def of(ctx) -> Ledger:
    if ctx.econ is None:
        ctx.econ = Ledger()
    return ctx.econ
