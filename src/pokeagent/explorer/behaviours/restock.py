"""restock: buy Poke Balls when the bag runs low (see explorer/restock.py for the rule); catch.py then has balls to throw."""
from __future__ import annotations

from pokeagent.explorer import restock as rs
from pokeagent.explorer import shop
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_hp
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
        balls, money = bag_contents(ctx.emu).get(rs.BALL_ID, 0), read_money(ctx.emu)
        if not st.get("intent"):
            if not rs.ball_buy_wanted(balls, money, st.get("tries", 0)) or ctx.step < st.get("next_check", 0):
                return None
            hp, mx = party_hp(ctx.emu)
            if mx and hp / mx < 0.5:
                return None  # heal first (the planner's Pokecenter trip)
            st["next_check"] = ctx.step + rs.RECHECK_EVERY
            marts = rs.candidate_marts(ctx.goals(), st.setdefault("failed", set()))
            if m not in marts and not self._path_to(ctx, lambda n: n[0] in marts):
                return None
            st.update(intent=True, steps=0)
            ctx.log(f"[restock: {balls} Poke Balls and {money} yen - going to a Mart]", "res")
        marts = rs.candidate_marts(ctx.goals(), st.get("failed", ()))
        st["steps"] = st.get("steps", 0) + 1
        if balls >= rs.BALL_MIN or st["steps"] > rs.MAX_TRIP_STEPS or not rs.ball_buy_wanted(balls, money, 0):
            return self._end(ctx, "trip over" if balls >= rs.BALL_MIN else f"gave up after {st['steps']} steps", failed=balls < rs.BALL_MIN)
        if m not in rs.MART_MAPS:
            path = self._path_to(ctx, lambda n: n[0] in marts)
            if path:
                return Decision(path[0], "restock_walk", f"{len(path)} steps to a Mart for Poke Balls")
            return self._end(ctx, "no route to a Mart", failed=True)
        return self._in_mart(ctx, m, x, y, money, balls)

    @staticmethod
    def _leave(ctx, st, m, x, y) -> Decision | None:
        """The purchase is done: walk out of the Mart instead of handing the room to the frontier (2026-11-06: ~1,000 presses
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

    def _in_mart(self, ctx, m, x, y, money, balls) -> Decision:
        spot = (m, *rs.SHOP_SPOT)
        if (m, x, y) == spot:
            if ctx.facing != rs.SHOP_FACING:
                return Decision(rs.SHOP_FACING, "restock_face", "facing the clerk")
            return self._buy(ctx, m, money, balls)
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((m, x, y), lambda n: n == spot)
        if p:
            return Decision(p[0], "restock_walk", f"{len(p)} steps to the clerk")
        # the Mart is not mapped yet: every Mart is the same room (door (3,7), up column 3 to row 5, then left to the counter)
        sx, sy = rs.SHOP_SPOT
        step = "UP" if y > sy and x == 3 else "LEFT" if x > sx else "RIGHT" if x < sx else "UP" if y > sy else "DOWN"
        return Decision(step, "restock_walk", "to the clerk (default Mart layout)")

    def _buy(self, ctx, m, money, balls) -> Decision:
        st = ctx.restock
        qty = rs.buy_quantity(money)
        st["tries"] = st.get("tries", 0) + 1
        res = shop.buy(ctx.emu, rs.BALL_ID, qty)
        ctx.log(f"[restock: bought {res.bought}/{qty} Poke Balls on map 0x{m:02X} for {res.money_before - res.money_after} yen "
                f"(balls {balls} -> {res.bag_after.get(rs.BALL_ID, 0)}, money {res.money_before} -> {res.money_after}); {res.reason}]", "res")
        if res.ok:
            st["bought"] = st.get("bought", 0) + res.bought
        else:
            st.setdefault("failed", set()).add(m)
        st["intent"], st["leave"] = False, True
        return no_press("restock_buy", f"{res.reason}: {res.bought} Poke Balls")

    @staticmethod
    def _end(ctx, why: str, failed: bool = False) -> Decision | None:
        st = ctx.restock
        st["intent"] = False
        st["leave"] = ctx.view.m in rs.MART_MAPS  # ended inside a Mart: walk out first
        if failed:
            st["tries"] = st.get("tries", 0) + 1
        ctx.log(f"[restock: {why}]", "res")
        return None
