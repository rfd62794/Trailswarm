"""plan_goal: the goal-directed planner (potion, leave the house, first pokemon, ... road to Pewter)."""
from __future__ import annotations

import random

from pokeagent.bandit.hook import heal_push_on, train_need
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import lead_level, party_hp, sprite_snapshot
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BATTLES_GYARADOS, GrindBudget
from pokeagent.explorer.training import gate_for, readiness_for, required_level, set_blackout_tax, stage_goal, team_for, under_level_note
from pokeagent.explorer import area_grind, par_follow, train_route
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.goals import GOALS
from pokeagent.knowledge import blackout_tax
from pokeagent.knowledge.cut_learner import LEARNER_STEP_CAP
from pokeagent.knowledge.encounters import level_ceiling
from pokeagent.knowledge.party import our_party
from pokeagent.knowledge.readiness import TEAM_GAP
from pokeagent.magikarp import BUY_STEP_CAP, EVOLVE_LEVEL, GYARADOS_STEP_CAP, GYARADOS_IDLE_CAP, MAGIKARP, MT_MOON_CENTER, party_species


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
        if goals_now_all["hm01_cut"] and not goals_now_all["cut_learner"]:
            ctx.cut_learner_steps += 1
            if ctx.cut_learner_steps > LEARNER_STEP_CAP:
                ctx.cut_learner_skipped = True
                ctx.log(f"[cut_learner: {LEARNER_STEP_CAP} steps without a Cut-capable party member - settled for this run]", "res")
            goals_now_all = ctx.goals()
        gyarados_stage = next((g for g in GOALS if not goals_now_all.get(g)), None) == "gyarados" and MAGIKARP in party_species(ctx.emu)
        if gyarados_stage:
            ctx.gyarados_steps += 1  # raising the trainee is the stage's work while it is the next goal
            if ctx.gyarados_steps > GYARADOS_STEP_CAP:
                ctx.gyarados_skipped = True
                ctx.log(f"[gyarados: {GYARADOS_STEP_CAP} steps with the goal open and a Magikarp in the party - settled for this run]", "res")
                goals_now_all = ctx.goals()
        if m == MT_MOON_CENTER and not goals_now_all["buy_magikarp"]:
            ctx.center_intent = "buy_magikarp"  # stay inside until the salesman has been dealt with
        elif ctx.center_intent == "buy_magikarp" and goals_now_all["buy_magikarp"]:
            ctx.center_intent = None  # bought (or no longer possible): the planner may walk out now
        ctx.stage_goal = stage_goal(goals_now_all)  # the stage record_battle_result taxes on a blackout
        extras = blackout_tax.extras(ctx.mem.data)
        set_blackout_tax(extras)  # every readiness_for caller sees the learned margins this step
        parcel = next(((i["map"], i["at"][0], i["at"][1], i.get("facing", "UP")) for i in ctx.mem.data.get("items", [])
                       if i.get("item") == "OAK'S PARCEL" and i.get("delta", 0) > 0), None)
        party_all = our_party(ctx.emu) if not ctx.view.battling else []   # real stats and moves; skipped mid-battle
        party = [c for c in party_all if c.name != "MAGIKARP"]  # the trainee never fights a boss: readiness judges the real team
        verdict = readiness_for(goals_now_all, party)
        if verdict and verdict.text != ctx.readiness_note:
            ctx.readiness_note = verdict.text
            extra = extras.get(ctx.stage_goal, 0.0)
            ctx.log(f"[readiness] {verdict.text} (score {verdict.score:+.2f}, need L{verdict.required})"
                    f"{f' (+{extra:.2f} blackout margin)' if extra > 0 else ''}", "res")
        team = team_for(goals_now_all, party_all)  # the hurt-lead verdict: is a second member useful for the boss?
        if team and team.text != ctx.team_note:
            ctx.team_note = team.text
            ctx.log(f"[readiness] {team.text}", "res")
        ctx.train_member = team.weakest.slot if team and team.weakest else None
        need, clamp = required_level(goals_now_all, ctx.opts.train_level, party)
        if clamp != ctx.clamp_note:
            ctx.clamp_note = clamp
            if clamp:
                ctx.log(f"[readiness] {clamp}", "res")
        ul = under_level_note(goals_now_all, party, ctx.opts.train_level)
        if ul != ctx.under_level_note:
            ctx.under_level_note = ul
            if ul:
                ctx.log(f"[readiness] {ul}", "res")
        need = self._team_need(goals_now_all, need, gyarados_stage)
        need = self._budgeted(ctx, goals_now_all, need, verdict)
        need_raw = need
        need = gate_for(m, need)  # never grind inside the cave: head for the exit, fight what blocks the way
        area_grind.note_map(ctx, m)
        need = area_grind.capped_need(ctx, m, need, lead_level(ctx.emu), bool(goals_now_all.get("to_route2")))
        need = train_need(ctx, goals_now_all, need)  # bandit decision point: grind or skip (unchanged when off)
        ctx.train_need = need  # frontier reads it to seek grass while below the target
        training_live = 0 < lead_level(ctx.emu) < need
        if gyarados_stage:
            self._gyarados_idle(ctx, training_live, lead_level(ctx.emu))
        else:
            ctx.gyarados_idle = 0  # left the stage: "consecutive" restarts on re-entry
        planned = plan_step({**goals_now_all, "_starter": ctx.opts.starter, "_blocked_now": frozenset(ctx.mem.temp_blocked), "_declined": set(ctx.declined_balls), "_hp": (hp_now, mx_now), "_push_on": heal_push_on(ctx, goals_now_all, hp_now, mx_now), "_parcel_spot": parcel,
                             "_level": lead_level(ctx.emu), "_train_level": need, "_heal_trips": ctx.heal_trips,
                             "_center_intent": ctx.center_intent, "_ladders": ctx.ladders, "_cave_plan": ctx.cave_plan, "_rom_route": ctx.rom_route, "_sprites": [(pic, sx - 4, sy - 4) for pic, sy, sx in sprite_snapshot(ctx.emu)], "_mom_failed": ctx.mom_failed_until > ctx.step,
                             "_respawn": ctx.emu.read(0xD719), "_need": need_raw, "_ship": ctx.__dict__.setdefault("ship_state", {}), "_ship_plan": ctx.ship_plan, "_ckpt_steps": ctx.__dict__.setdefault("ckpt_steps", {})},
                            ctx.mem.data["maps"], (m, x, y), ctx.facing)
        ctx.train_route_live = bool(gyarados_stage and training_live)
        if planned is None and gyarados_stage and training_live:
            planned = train_route.step(ctx.mem.data["maps"], (m, x, y), ctx.mem.temp_blocked, hp_now, mx_now)  # no planner target: go to the grass
        if planned and planned[1].startswith("goal checkpoint"):
            ck = ctx.__dict__["ckpt_steps"]; ck[5] = ck.get(5, 0) + 1  # Vermilion is the only checkpoint town so far
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
    def _team_need(goals: dict, need: int, has_magikarp: bool) -> int:
        """At the gyarados stage with a Magikarp in the party, level the trainee until useful: the lead reads
        min(fighter, trainee + TEAM_GAP), so the gate needs EVOLVE_LEVEL + TEAM_GAP to hold until Gyarados."""
        if has_magikarp and next((g for g in GOALS if not goals.get(g)), None) == "gyarados":
            return max(need, EVOLVE_LEVEL + TEAM_GAP)
        return need

    @staticmethod
    def _gyarados_idle(ctx: ExplorerContext, training_live: bool, level: int | None = None) -> None:
        """Settle the gyarados goal early when the gate is closed or lifted so the stage has nothing to do."""
        gained = level is not None and level > getattr(ctx, "gyarados_idle_level", 0)
        if level is not None:
            ctx.gyarados_idle_level = level
        ctx.gyarados_idle = 0 if training_live or gained else ctx.gyarados_idle + 1  # a level gain is progress too
        if ctx.gyarados_idle >= GYARADOS_IDLE_CAP and not ctx.gyarados_skipped:
            ctx.gyarados_skipped = True
            ctx.log(f"[gyarados: training gate closed or lifted for {GYARADOS_IDLE_CAP} plan steps - settled for this run]", "res")

    @staticmethod
    def _budgeted(ctx: ExplorerContext, goals: dict, need: int, verdict) -> int:
        """The training level, or 0 (gate lifted) once the grind budget for this goal is spent."""
        stage, level = stage_goal(goals), lead_level(ctx.emu)
        if stage is None:
            return need
        gy = next((g for g in GOALS if not goals.get(g)), None) == "gyarados"
        goal = "gyarados" if gy else stage  # the gyarados stage has its own budget key: it must not accrue on the next boss's
        ctx.grind = ctx.grind or GrindBudget()
        why = ctx.grind.update(goal, level=level, step=ctx.step, battles=ctx.battles, blackouts=ctx.blackouts_row,
                               training=0 < level < need, ceiling=level_ceiling(stage),
                               max_battles=GRIND_BATTLES_GYARADOS if gy else GRIND_BATTLES)
        if why:
            ctx.log(f"[readiness] grind budget spent for {goal}: {why}; lifting the training gate", "res")
        return 0 if ctx.grind.lifted(goal) else need
