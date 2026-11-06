"""plan_goal: the goal-directed planner (potion, leave the house, first pokemon, ... road to Pewter)."""
from __future__ import annotations

import random

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import lead_level, party_hp, sprite_snapshot
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.training import train_level_for
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.magikarp import BUY_STEP_CAP, MT_MOON_CENTER


class PlanGoal(BehaviourBase):
    name = "plan_goal"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # plan_step answers None when the learned world cannot reach the next goal yet

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        hp_now, mx_now = party_hp(ctx.emu)
        if ctx.center_intent and m not in POKECENTER_MAPS:
            ctx.center_intent = None  # left the center: the intent is spent
        goals_now_all = ctx.goals()
        if not goals_now_all["buy_magikarp"] and m in (MT_MOON_CENTER, 0x0F):
            ctx.buy_steps += 1
            if ctx.buy_steps > BUY_STEP_CAP:
                ctx.buy_skipped = True; ctx.center_intent = None
                ctx.log(f"[buy_magikarp: {BUY_STEP_CAP} steps in/around the Mt Moon Pokemon Center without buying - settled for this run]", "res")
                goals_now_all = ctx.goals()
        if m == MT_MOON_CENTER and not goals_now_all["buy_magikarp"]:
            ctx.center_intent = "buy_magikarp"  # stay inside until the salesman has been dealt with
        elif ctx.center_intent == "buy_magikarp" and goals_now_all["buy_magikarp"]:
            ctx.center_intent = None  # bought (or no longer possible): the planner may walk out now
        parcel = next(((i["map"], i["at"][0], i["at"][1], i.get("facing", "UP")) for i in ctx.mem.data.get("items", [])
                       if i.get("item") == "OAK'S PARCEL" and i.get("delta", 0) > 0), None)
        planned = plan_step({**goals_now_all, "_starter": ctx.opts.starter, "_declined": set(ctx.declined_balls), "_hp": (hp_now, mx_now), "_parcel_spot": parcel,
                             "_level": lead_level(ctx.emu), "_train_level": train_level_for(goals_now_all, ctx.opts.train_level),
                             "_center_intent": ctx.center_intent, "_sprites": [(pic, sx - 4, sy - 4) for pic, sy, sx in sprite_snapshot(ctx.emu)], "_mom_failed": ctx.mom_failed_until > ctx.step},
                            ctx.mem.data["maps"], (m, x, y), ctx.facing)
        if planned and "at Mom, talking" in planned[1]:
            ctx.mom_talk_step = ctx.step; ctx.mom_talk_hp = hp_now
            ctx.slow_until = ctx.step + 12  # healing has a fade: slow down so completion is recognised
        if planned and not (ctx.explore_run and m != 0x28 and random.random() < 0.3):  # never gamble in the lab
            return Decision(planned[0], "plan_goal", planned[1])
        return None
