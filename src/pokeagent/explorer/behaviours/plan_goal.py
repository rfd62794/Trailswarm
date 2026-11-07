"""plan_goal: the goal-directed planner (potion, leave the house, first pokemon, ... road to Pewter)."""
from __future__ import annotations

import random

from pokeagent.bandit.hook import heal_push_on, train_need
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import lead_level, party_hp, sprite_snapshot
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.grind import GrindBudget
from pokeagent.explorer.training import gate_for, readiness_for, required_level, stage_goal
from pokeagent.explorer import area_grind, par_follow
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.knowledge.encounters import level_ceiling
from pokeagent.knowledge.party import our_party
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
        party = our_party(ctx.emu) if not ctx.view.battling else []   # real stats and moves; skipped mid-battle
        party = [c for c in party if c.name != "MAGIKARP"]  # the trainee never fights a boss: readiness judges the real team
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
        need = gate_for(m, need)  # never grind inside the cave: head for the exit, fight what blocks the way
        area_grind.note_map(ctx, m)
        need = area_grind.capped_need(ctx, m, need, lead_level(ctx.emu), bool(goals_now_all.get("to_route2")))
        need = train_need(ctx, goals_now_all, need)  # bandit decision point: grind or skip (unchanged when off)
        ctx.train_need = need  # frontier reads it to seek grass while below the target
        planned = plan_step({**goals_now_all, "_starter": ctx.opts.starter, "_blocked_now": frozenset(ctx.mem.temp_blocked), "_declined": set(ctx.declined_balls), "_hp": (hp_now, mx_now), "_push_on": heal_push_on(ctx, goals_now_all, hp_now, mx_now), "_parcel_spot": parcel,
                             "_level": lead_level(ctx.emu), "_train_level": need, "_heal_trips": ctx.heal_trips,
                             "_center_intent": ctx.center_intent, "_ladders": ctx.ladders, "_cave_plan": ctx.cave_plan, "_rom_route": ctx.rom_route, "_sprites": [(pic, sx - 4, sy - 4) for pic, sy, sx in sprite_snapshot(ctx.emu)], "_mom_failed": ctx.mom_failed_until > ctx.step},
                            ctx.mem.data["maps"], (m, x, y), ctx.facing)
        if planned and "at Mom, talking" in planned[1]:
            ctx.mom_talk_step = ctx.step; ctx.mom_talk_hp = hp_now
            ctx.slow_until = ctx.step + 12  # healing has a fade: slow down so completion is recognised
        driver = ""
        if planned and ctx.opts.par_follow:
            planned, driver = par_follow.refine(ctx, planned, [(pic, sx - 4, sy - 4) for pic, sy, sx in sprite_snapshot(ctx.emu)])
        if planned and not (ctx.explore_run and m != 0x28 and random.random() < 0.3):  # never gamble in the lab
            return Decision(planned[0], "plan_goal", planned[1], driver=driver)
        return None

    @staticmethod
    def _budgeted(ctx: ExplorerContext, goals: dict, need: int, verdict) -> int:
        """The training level, or 0 (gate lifted) once the grind budget for this goal is spent."""
        goal, level = stage_goal(goals), lead_level(ctx.emu)
        if goal is None:
            return need
        ctx.grind = ctx.grind or GrindBudget()
        why = ctx.grind.update(goal, level=level, step=ctx.step, battles=ctx.battles, blackouts=ctx.blackouts_row,
                               training=0 < level < need, ceiling=level_ceiling(goal))
        if why:
            ctx.log(f"[readiness] grind budget spent for {goal}: {why}; lifting the training gate", "res")
        return 0 if ctx.grind.lifted(goal) else need
