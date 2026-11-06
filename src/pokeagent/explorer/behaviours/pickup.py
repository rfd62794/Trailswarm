"""pickup: grab a nearby item ball (pic 61) while no goal route is more important.

Sits after ``plan_goal`` and before ``frontier``: it only fires while the planner has no
goal-critical route, detours at most ``PICKUP_DETOUR`` tiles to a ball's side, faces it and
presses A; ``advance_dialog`` (earlier in the order) closes the box. A ball that gave no
item text twice in a run is skipped for the rest of that run (``ctx.pickup_tries``, in-memory).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pokeagent.explorer import items
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.perceive import DIRS

if TYPE_CHECKING:
    from pokeagent.explorer.context import ExplorerContext

PICKUP_DETOUR = 20  # most steps a pickup may cost from here (the named detour budget)
_LAB = 0x28         # Oak's lab: before first_pokemon the starter planner owns the balls
_MAX_TRIES = 2      # presses facing a ball that gave no item text before it is skipped this run


class Pickup(BehaviourBase):
    name = "pickup"

    def applies(self, ctx: "ExplorerContext") -> bool:
        if ctx.view.box or ctx.view.battling:
            return False  # dialog/battle behaviours earlier in the order own those steps
        if ctx.pickup_await is not None:
            return True  # a pressed ball owes a result check
        return self._choose(ctx) is not None

    def step(self, ctx: "ExplorerContext") -> Decision | None:
        self._resolve(ctx)
        live = {(bx, by) for _slot, bx, by in items.item_balls(ctx.emu)}
        if ctx.pickup_ball is not None and ctx.pickup_ball[1:] not in live:
            ctx.pickup_ball = None  # the committed ball is gone from the sprite table: re-pick below
        plan = self._plan(ctx, ctx.pickup_ball) if ctx.pickup_ball is not None else None
        if plan is None:
            ctx.pickup_ball = None  # the committed ball is gone or unreachable: re-pick below
            plan = self._choose(ctx)
            if plan is None:
                return None
            ctx.pickup_ball = plan["ball"]
        return self._act(ctx, plan)

    def _gated(self, ctx: "ExplorerContext") -> bool:
        """Goals/scenes where a pickup detour is forbidden."""
        goals = ctx.goals()
        if goal_stage(goals) == "deliver_parcel":
            return True  # carrying Oak's parcel: no detours (the planner's rule for training too)
        return ctx.view.m == _LAB and not goals.get("first_pokemon")

    def _choose(self, ctx: "ExplorerContext") -> dict | None:
        """The cheapest reachable ball on this map: {"ball", "spot", "face", "route", "steps"} or None."""
        if self._gated(ctx):
            return None
        m = ctx.view.m
        best = None
        for _slot, bx, by in items.item_balls(ctx.emu):  # the sprite table is the current map's
            ball = (m, bx, by)
            if ctx.pickup_tries.get(ball, 0) >= _MAX_TRIES:
                continue
            plan = self._plan(ctx, ball)
            if plan is not None and (best is None or plan["steps"] < best["steps"]):
                best = plan
        return best

    def _plan(self, ctx: "ExplorerContext", ball: tuple) -> dict | None:
        """Route to a tile beside ``ball`` and the facing that looks at it, within PICKUP_DETOUR."""
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        if ball[0] != m:
            return None
        _m, bx, by = ball
        best = None
        for face, (ddx, ddy) in DIRS.items():
            spot = (bx - ddx, by - ddy)  # stand here facing `face`: pos + DIRS[face] == the ball
            route = ctx.mem.route_to(m, x, y, (m, spot[0], spot[1]))
            if route is None:
                continue
            _node, buttons = route
            if len(buttons) > PICKUP_DETOUR:
                continue
            if best is None or len(buttons) < best["steps"]:
                best = {"ball": ball, "spot": spot, "face": face, "route": buttons, "steps": len(buttons)}
        return best

    def _act(self, ctx: "ExplorerContext", plan: dict) -> Decision:
        if (ctx.view.x, ctx.view.y) == plan["spot"]:
            if ctx.facing != plan["face"]:
                return Decision(plan["face"], "pickup",
                                f"item ball at ({plan['ball'][1]},{plan['ball'][2]}): turn to face it")
            ctx.pickup_await = plan["ball"]
            return Decision("A", "pickup",
                            f"item ball at ({plan['ball'][1]},{plan['ball'][2]}): pressing A to pick it up")
        return Decision(plan["route"][0], "pickup",
                        f"item ball at ({plan['ball'][1]},{plan['ball'][2]}): {len(plan['route'])} steps to its side")

    def _resolve(self, ctx: "ExplorerContext") -> None:
        """The awaited A press is done (the box closed): did the ball give item text?"""
        ball = ctx.pickup_await
        if ball is None:
            return
        ctx.pickup_await = None
        ctx.pickup_ball = None
        m, bx, by = ball
        e = ctx.mem.m(m).get("items", {}).get(f"{bx},{by}") or {}
        if e.get("item"):
            ctx.log(f"[pickup: the ball at ({bx},{by}) gave {e['item']}]", "res")
        else:
            ctx.pickup_tries[ball] = ctx.pickup_tries.get(ball, 0) + 1
            ctx.log(f"[pickup: no item text from the ball at ({bx},{by}) "
                    f"({ctx.pickup_tries[ball]}/{_MAX_TRIES})]", "res")
