"""plan_goal: the goal-directed planner (potion, leave the house, first pokemon, ... road to Pewter)."""
from __future__ import annotations

import random

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.grind import GrindBudget
from pokeagent.explorer.training import readiness_for, required_level, stage_goal
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.knowledge.encounters import level_ceiling
from pokeagent.knowledge.party import our_party


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
        parcel = next(((i["map"], i["at"][0], i["at"][1], i.get("facing", "UP")) for i in ctx.mem.data.get("items", [])
                       if i.get("item") == "OAK'S PARCEL" and i.get("delta", 0) > 0), None)
        party = our_party(ctx.emu) if not ctx.view.battling else []   # real stats and moves; skipped mid-battle
        verdict = readiness_for(goals_now_all, party)
        if verdict and verdict.text != ctx.readiness_note:
            ctx.readiness_note = verdict.text
            ctx.log(f"[readiness] {verdict.text} (score {verdict.score:+.2f}, need L{verdict.required})", "res")
        need, clamp = required_level(goals_now_all, ctx.opts.train_level, party)
        if clamp != ctx.clamp_note:
            ctx.clamp_note = clamp
            if clamp:
                ctx.log(f"[readiness] {clamp}", "res")
        need = self._budgeted(ctx, goals_now_all, need, verdict)
        planned = plan_step({**goals_now_all, "_starter": ctx.opts.starter, "_declined": set(ctx.declined_balls), "_hp": (hp_now, mx_now), "_parcel_spot": parcel,
                             "_level": ctx.emu.read(0xD18C), "_train_level": need,
                             "_center_intent": ctx.center_intent, "_mom_failed": ctx.mom_failed_until > ctx.step},
                            ctx.mem.data["maps"], (m, x, y), ctx.facing)
        if planned and "at Mom, talking" in planned[1]:
            ctx.mom_talk_step = ctx.step; ctx.mom_talk_hp = hp_now
            ctx.slow_until = ctx.step + 12  # healing has a fade: slow down so completion is recognised
        if planned and not (ctx.explore_run and m != 0x28 and random.random() < 0.3):  # never gamble in the lab
            return Decision(planned[0], "plan_goal", planned[1])
        return None

    @staticmethod
    def _budgeted(ctx: ExplorerContext, goals: dict, need: int, verdict) -> int:
        """The training level, or 0 (gate lifted) once the grind budget for this goal is spent."""
        goal, level = stage_goal(goals), ctx.emu.read(0xD18C)
        if goal is None:
            return need
        ctx.grind = ctx.grind or GrindBudget()
        why = ctx.grind.update(goal, level=level, step=ctx.step, battles=ctx.battles, blackouts=ctx.blackouts_row,
                               training=0 < level < need, ceiling=level_ceiling(goal))
        if why:
            ctx.log(f"[readiness] grind budget spent for {goal}: {why}; lifting the training gate", "res")
        return 0 if ctx.grind.lifted(goal) else need
