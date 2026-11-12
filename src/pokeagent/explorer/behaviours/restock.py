"""restock: one Mart visit that sells the whitelisted Nuggets and buys the shopping list (explorer/economy): balls the catch
need-list requires, Potions, an Escape Rope before a cave. Walking rules and caps are explorer/restock.py's."""
from __future__ import annotations

from pokeagent.explorer import restock as rs
from pokeagent.explorer import shop
from pokeagent.explorer.economy import budget, floor, ledger, plan
from pokeagent.explorer.economy.prices import price, stocked
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_needs_heal
from pokeagent.explorer.world import WorldGraph
from pokeagent.goals import bag_contents
from pokeagent.ramworld import read_money


class Restock(BehaviourBase):
    name = "restock"

    def applies(self, ctx: ExplorerContext) -> bool:
        return not ctx.view.battling and not ctx.view.box and ctx.center_intent is None

    def step(self, ctx: ExplorerContext) -> Decision | None:
        st = ctx.restock
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        if st.get("leave"):
            return self._leave(ctx, st, m, x, y)
        if not st.get("intent"):
            if st.get("tries", 0) >= rs.MAX_TRIES or ctx.step < st.get("next_check", 0):
                return None
            if party_needs_heal(ctx.emu, 0.5):
                return None  # heal first (the planner's Pokecenter trip)
            st["next_check"] = ctx.step + rs.RECHECK_EVERY
            trip = plan.trip_plan(ctx)
            if trip is None:
                return None
            st["want"] = tuple(i for i, _ in trip.items)  # only a Mart that sells one of these is worth the walk
            marts = self._marts(ctx, st, st.setdefault("failed", set()))
            if m not in marts and not self._path_to(ctx, lambda n: n[0] in marts):
                return None
            st.update(intent=True, steps=0)
            ctx.shop_intent = ("mart", None)  # par_follow: this is a Mart trip
            ctx.log(f"[restock: {self._describe(trip)} - going to a Mart]", "res")
        marts = self._marts(ctx, st, st.get("failed", ()))
        st["steps"] = st.get("steps", 0) + 1
        if st["steps"] > rs.MAX_TRIP_STEPS:
            return self._end(ctx, f"gave up after {st['steps']} steps", failed=True)
        if st["steps"] % 10 == 0 and plan.trip_plan(ctx) is None:
            return self._end(ctx, "nothing left to do at a Mart")
        if m not in rs.MART_MAPS:
            path = self._path_to(ctx, lambda n: n[0] in marts)
            if path:
                return Decision(path[0], "restock_walk", f"{len(path)} steps to a Mart")
            return self._end(ctx, "no route to a Mart", failed=True)
        return self._in_mart(ctx, m, x, y)

    @staticmethod
    def _marts(ctx, st, failed) -> frozenset:
        """Candidate Marts that sell what the trip wants (the Vermilion Mart has Balls and Super Potions but no Potion)."""
        marts = rs.candidate_marts(ctx.goals(), failed)
        return floor.marts_selling([(i, 1) for i in st.get("want", ())], marts) if st.get("want") else marts

    @staticmethod
    def _describe(trip) -> str:
        return ", ".join([f"sell {len(trip.sell)} NUGGET"] * bool(trip.sell) + [f"buy {q}x item 0x{i:02X}" for i, q in trip.items])

    @staticmethod
    def _leave(ctx, st, m, x, y) -> Decision | None:
        """The visit is done: walk out of the Mart instead of handing the room to the frontier (2026-11-06: ~1,000 presses
        exploring Cerulean's Mart after buying, and a re-entry from the street later - the 3<->67 loop)."""
        st["leave_steps"] = st.get("leave_steps", 0) + 1
        if m not in rs.MART_MAPS or st["leave_steps"] > rs.MAX_LEAVE_STEPS:
            st["leave"], st["leave_steps"] = False, 0
            return None
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((m, x, y), lambda n: n[0] != m)
        if p:
            return Decision(p[0], "restock_leave", f"{len(p)} steps out of the Mart")
        door_x = rs.DOOR[0]  # not mapped: every Mart has the door at (3,7), straight down column 3
        return Decision("RIGHT" if x < door_x else "LEFT" if x > door_x else "DOWN", "restock_leave", "out of the Mart (default layout)")

    @staticmethod
    def _path_to(ctx, goal_fn) -> list[str] | None:
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path(ctx.pos(), goal_fn, 5000)
        return p if p and len(p) <= rs.MAX_PATH else None

    def _in_mart(self, ctx, m, x, y) -> Decision:
        spot = (m, *rs.SHOP_SPOT)
        if (m, x, y) == spot:
            if ctx.facing != rs.SHOP_FACING:
                return Decision(rs.SHOP_FACING, "restock_face", "facing the clerk")
            return self._visit(ctx, m)
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((m, x, y), lambda n: n == spot)
        if p:
            return Decision(p[0], "restock_walk", f"{len(p)} steps to the clerk")
        # the Mart is not mapped yet: every Mart is the same room (door (3,7), up column 3 to row 5, then left to the counter)
        sx, sy = rs.SHOP_SPOT
        step = "UP" if y > sy and x == 3 else "LEFT" if x > sx else "RIGHT" if x < sx else "UP" if y > sy else "DOWN"
        return Decision(step, "restock_walk", "to the clerk (default Mart layout)")

    def _visit(self, ctx, m) -> Decision:
        """At the counter: sell the whitelisted Nuggets first (more money), then buy the list, never below the reserve."""
        st, led = ctx.restock, ledger.of(ctx)
        st["tries"] = st.get("tries", 0) + 1
        ok = True
        trip = plan.trip_plan(ctx)
        for item in trip.sell if trip else ():
            r = shop.sell(ctx.emu, item)
            ctx.log(f"[economy: sold NUGGET on map 0x{m:02X} for {r.gained} yen (money {r.money_before} -> {r.money_after}); {r.reason}]", "res")
            if not r.ok:
                ok = False
                break
            led.sale(ctx, item, r.money_before, r.money_after)
        bag, money = bag_contents(ctx.emu), read_money(ctx.emu)
        led.ref_money, led.ref_step = max(money, led.reserve_ref(ctx.step)), ctx.step
        reserve = budget.reserve(ctx.goals(), money, led.ref_money)
        unsold = st.setdefault("unsold", {})
        listed = plan.make_list(ctx, bag, money, mart=m, stock=lambda i, mm: stocked(i, mm) and i not in unsold.get(mm, ())) if ok else ()
        for item, qty in listed:
            if item in st.setdefault("unsold", {}).get(m, ()) or not stocked(item, m):
                continue
            qty = min(qty, max(0, (read_money(ctx.emu) - reserve) // max(1, price(item))))  # the reserve is never breached
            if qty < 1:
                continue
            res = shop.buy(ctx.emu, item, qty)
            ctx.log(f"[economy: bought {res.bought}/{qty} x item 0x{item:02X} on map 0x{m:02X} for {res.money_before - res.money_after} yen "
                    f"(money {res.money_before} -> {res.money_after}); {res.reason}]", "res")
            led.stock_seen[m] = shop.stock(ctx.emu) or led.stock_seen.get(m, [])  # best effort: wItemList as the clerk left it
            if res.bought:
                led.purchase(ctx, item, res.bought, res.money_before, res.money_after)
                st["bought"] = st.get("bought", 0) + res.bought
            if res.reason == "not_sold_here":
                st["unsold"].setdefault(m, set()).add(item)  # this Mart's stock lacks it: read live, not hard-coded
            elif not res.ok:
                st.setdefault("failed", set()).add(m)
                break
        if not ok:
            st.setdefault("failed", set()).add(m)
        st["intent"], st["leave"] = False, True
        ctx.shop_intent = None
        return no_press("restock_buy", "Mart visit done")

    @staticmethod
    def _end(ctx, why: str, failed: bool = False) -> Decision | None:
        st = ctx.restock
        st["intent"] = False
        st["leave"] = ctx.view.m in rs.MART_MAPS  # ended inside a Mart: walk out first
        ctx.shop_intent = None
        if failed:
            st["tries"] = st.get("tries", 0) + 1
        ctx.log(f"[restock: {why}]", "res")
        return None
