"""magikarp_deferral: the circle-back half of the buy_magikarp plan.

Arriving at the Mt Moon Pokemon Center (0x44) too poor to buy used to latch ``buy_skipped`` for good,
even when the money was one trainer fight away. Now ``magikarp.magikarp_goal_settled`` latches
``buy_deferred`` instead (a full party still skips at once - walking fixes money, not a sixth slot),
and this module's ``tick`` - called once per plan_goal step where the old buy_steps block sat - counts
the wait, watches for the money to be worth the walk back, and keeps the budget floor up meanwhile.
"""
from __future__ import annotations

import pokeagent.magikarp_reserve as magikarp_reserve
from pokeagent.explorer.economy import budget
from pokeagent.explorer.world import WorldGraph
from pokeagent.magikarp import BUY_STEP_CAP, MT_MOON_CENTER
from pokeagent.ramstructs import PARTY_COUNT
from pokeagent.ramworld import read_money

ROUTE4 = 0x0F   # the active attempt's "in/around the center" pair with MT_MOON_CENTER (the old plan_goal block)


def deferred(ctx) -> bool:
    """The goal is open but paused (poor at 0x44): the planner's _buy_deferred flag; plan_step stays off
    the salesman's trail while the agent earns west of Mt Moon."""
    return bool(ctx.get("buy_deferred"))


def _path_to_center(ctx) -> int | None:
    """Strict learned-graph steps from where we stand to map 0x44, or None. ``_bfs_node``, not ``path()``:
    a successful ``path`` stamps WorldGraph.last_route, which is par_follow's planner target."""
    g = WorldGraph(ctx.mem.data.get("maps", {}))
    g.blocked_now = frozenset(ctx.mem.temp_blocked)
    found = g._bfs_node(ctx.pos(), lambda n: n[0] == MT_MOON_CENTER, 5000)
    return len(found[1]) if found else None


def tick(ctx, m: int) -> dict:
    """One plan_goal step of buy_magikarp bookkeeping; returns the refreshed ctx.goals().

    Goal open and NOT deferred: ``buy_steps`` counts steps in/around the center (cap BUY_STEP_CAP,
    unchanged from the old plan_goal block). Goal deferred: ``deferred_steps`` counts every step while
    Mt Moon 1F stays unseen, on any map - never reset, so repeated blackouts cannot extend the wait -
    and should_circle_back restarts the normal buy attempt. The two never count together.
    """
    seen = ctx.seen_maps
    if not ctx.goals().get("buy_magikarp"):
        if ctx.get("buy_deferred"):
            if 0x3B not in seen:
                ctx.deferred_steps = ctx.get("deferred_steps", 0) + 1
                if ctx.deferred_steps > magikarp_reserve.CIRCLE_BACK_STEP_CAP:
                    ctx.buy_deferred, ctx.buy_skipped, ctx.center_intent = False, True, None
                    ctx.log(f"[buy_magikarp: {magikarp_reserve.CIRCLE_BACK_STEP_CAP} steps deferred west of Mt Moon - settled for this run]", "res")
                else:
                    path_len = _path_to_center(ctx)
                    if magikarp_reserve.should_circle_back(read_money(ctx.emu), ctx.emu.read(PARTY_COUNT), m, path_len):
                        ctx.buy_deferred, ctx.buy_steps = False, 0
                        ctx.log(f"[buy_magikarp: money restored ({read_money(ctx.emu)} yen) - circling back to the Mt Moon Pokemon Center ({path_len} steps)]", "res")
        elif m in (MT_MOON_CENTER, ROUTE4):
            ctx.buy_steps += 1
            if ctx.buy_steps > BUY_STEP_CAP:
                ctx.buy_skipped = True; ctx.center_intent = None
                ctx.log(f"[buy_magikarp: {BUY_STEP_CAP} steps in/around the Mt Moon Pokemon Center without buying - settled for this run]", "res")
    budget.set_magikarp_floor(magikarp_reserve.magikarp_floor(ctx, seen))
    return ctx.goals()


def sync_center_intent(ctx, m: int, goals: dict) -> None:
    """The center-intent branches of plan_goal, moved wholesale. While deferred the agent must walk out
    and earn, so a "buy_magikarp" intent is cleared and never set; the old two branches apply otherwise."""
    if ctx.get("buy_deferred"):
        if ctx.center_intent == "buy_magikarp":
            ctx.center_intent = None
        return
    if m == MT_MOON_CENTER and not goals["buy_magikarp"]:
        ctx.center_intent = "buy_magikarp"  # stay inside until the salesman has been dealt with
    elif ctx.center_intent == "buy_magikarp" and goals["buy_magikarp"]:
        ctx.center_intent = None  # bought (or no longer possible): the planner may walk out now
