"""plan_goal: the goal-directed planner (potion, leave the house, first pokemon, ... road to Pewter)."""
from __future__ import annotations

import random

from pokeagent.bandit.hook import heal_push_on, train_need
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.status_care import of as care_state
from pokeagent.explorer.trainee_gate import trainee_ok
from pokeagent.explorer.perceive import heal_gate_hp, lead_level, party_hp, sprite_snapshot
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BATTLES_GYARADOS, GrindBudget, best_level, grinding_now, stall_hold_holds, STALL_HOLD_CAP
from pokeagent.explorer.training import boss_need_for, gate_for, readiness_for, required_level, set_blackout_tax, stage_goal, team_for, under_level_note
from pokeagent.explorer import party_log, area_grind, grind_episode, magikarp_deferral, par_follow, retalk_memory, train_route
from pokeagent.explorer.world import POKECENTER_MAPS, WorldGraph
from pokeagent.goals import GOALS
from pokeagent.grind import stage_maps
from pokeagent.knowledge import blackout_tax, team_plan, trainers
from pokeagent.knowledge.cut_learner import LEARNER_STEP_CAP
from pokeagent.knowledge.encounters import TRAIN_MAP, level_ceiling
from pokeagent.knowledge.party import our_party
from pokeagent.knowledge.readiness import TEAM_GAP
from pokeagent.magikarp import EVOLVE_LEVEL, GYARADOS_STEP_CAP, GYARADOS_IDLE_CAP, MAGIKARP, party_species, trainee_slot


class PlanGoal(BehaviourBase):
    name = "plan_goal"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # plan_step answers None when the learned world cannot reach the next goal yet

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        hp_now, _ = party_hp(ctx.emu)
        if ctx.center_intent and m not in POKECENTER_MAPS:
            ctx.center_intent = None  # left the center: the intent is spent
        goals_now_all = ctx.goals()
        goals_now_all = magikarp_deferral.tick(ctx, m)
        if goals_now_all["hm01_cut"] and not goals_now_all["cut_learner"]:
            ctx.cut_learner_steps += 1
            if ctx.cut_learner_steps > LEARNER_STEP_CAP:
                ctx.cut_learner_skipped = True
                ctx.log(f"[cut_learner: {LEARNER_STEP_CAP} steps without a Cut-capable party member - settled for this run]", "res")
            goals_now_all = ctx.goals()
        team_ready_stage = next((g for g in GOALS if not goals_now_all.get(g)), None) == "team_ready"
        if team_ready_stage:
            ctx.team_ready_steps += 1  # building the team is the stage's work while it is the next goal
            if ctx.team_ready_steps > GYARADOS_STEP_CAP:
                ctx.team_ready_skipped = True
                ctx.log(f"[team_ready: {GYARADOS_STEP_CAP} steps with the goal open - settled for this run]", "res")
                goals_now_all = ctx.goals()
        magikarp_deferral.sync_center_intent(ctx, m, goals_now_all)
        ctx.stage_goal = stage_goal(goals_now_all)  # the stage record_battle_result taxes on a blackout
        extras = blackout_tax.extras(ctx.mem.data)
        set_blackout_tax(extras)  # every readiness_for caller sees the learned margins this step
        parcel = next(((i["map"], i["at"][0], i["at"][1], i.get("facing", "UP")) for i in ctx.mem.data.get("items", [])
                       if i.get("item") == "OAK'S PARCEL" and i.get("delta", 0) > 0), None)
        party_all = our_party(ctx.emu) if not ctx.view.battling else []   # real stats and moves; skipped mid-battle
        party = [c for c in party_all if c.name != "MAGIKARP"]  # the trainee never fights a boss: readiness judges the real team
        verdict = readiness_for(goals_now_all, party)
        nv = boss_need_for(goals_now_all, party_all)  # the TEAM gate: judges every slot, not only the lead
        st = team_plan.of(ctx)
        st["breakers"] = team_plan.band_breakers(party_all, team_plan.level_band(party_all, nv.need)) if nv else ()
        note = nv.text if nv else (verdict.text if verdict else "")
        if note and note != ctx.readiness_note:
            ctx.readiness_note = note
            extra = extras.get(ctx.stage_goal, 0.0)
            score = nv.team_score if nv else verdict.score
            weak = f", weak slots {','.join(str(s + 1) for s in nv.weak_slots)}" if nv and nv.weak_slots else ""
            lead = f", lead slot {nv.lead_slot + 1}" if nv else ""
            ctx.log(f"[readiness] {note} (score {score:+.2f}, need L{nv.need if nv else verdict.required}{lead}{weak})"
                    f"{f' (+{extra:.2f} blackout margin)' if extra > 0 else ''}", "res")
        team = team_for(goals_now_all, party_all)  # the hurt-lead verdict: is a second member useful for the boss?
        if team and team.text != ctx.team_note:
            ctx.team_note = team.text
            ctx.log(f"[readiness] {team.text}", "res")
        ctx.train_member = team.weakest.slot if team and team.weakest else None
        if not ctx.view.battling and ctx.center_intent is None and (ctx.train_member is not None or MAGIKARP in party_species(ctx.emu)):
            if not trainee_ok(ctx).ok and care_state(ctx).get("walk") is not None:
                ctx.gym_hold_seen = (ctx.step, True); return None  # not judged this step: goal_talk must not walk to the leader meanwhile  # never train a fainted trainee: the heal walk (StatusCare) owns the steps until it lands
        if team_ready_stage:
            if team is None:
                ctx.team_ready_nodata = True  # no ROM/boss data: never block the route
            elif team.ready:
                ctx.team_ready_ok = ctx.had_team_ready = True  # the sim says the party beats the next boss
            else:
                ctx.team_ready_ok = False
        need, clamp = required_level(goals_now_all, ctx.opts.train_level, party_all)
        if clamp != ctx.clamp_note:
            ctx.clamp_note = clamp
            if clamp:
                ctx.log(f"[readiness] {clamp}", "res")
        ul = under_level_note(goals_now_all, party_all, ctx.opts.train_level)
        if ul != ctx.under_level_note:
            ctx.under_level_note = ul
            if ul:
                ctx.log(f"[readiness] {ul}", "res")
        need = self._team_need(ctx, goals_now_all, need)
        need = self._budgeted(ctx, goals_now_all, need, verdict, party)
        need_raw = need
        need = gate_for(m, need)  # never grind inside the cave: head for the exit, fight what blocks the way
        area_grind.note_map(ctx, m)
        need = area_grind.capped_need(ctx, m, need, lead_level(ctx.emu), bool(goals_now_all.get("to_route2")))
        need = train_need(ctx, goals_now_all, need)  # bandit decision point: grind or skip (unchanged when off)
        ctx.train_need = need  # frontier reads it to seek grass while below the target
        lead = lead_level(ctx.emu)
        pressure = team_plan.grind_pressure(party_all, need, self._boss_gap(ctx, m, x, y), ctx.blackouts_row,
                                            breakers=st.get("breakers", ()), ready=bool(nv and nv.ready), lead_level=lead)
        if pressure != st.get("pressure"):
            ctx.log(f"[team_plan: grind pressure {st.get('pressure')} -> {pressure}]", "res")
            st["pressure"] = pressure
        if pressure >= team_plan.GRIND_PRESSURE_START and need > 0:
            if not st.get("grinding"):
                ctx.log(f"[team_plan: grind latch on at pressure {pressure:.2f}]", "res")
            st["grinding"] = True
        elif pressure < team_plan.GRIND_PRESSURE_STOP and st.pop("grinding", None):
            ctx.log(f"[team_plan: grind latch off at pressure {pressure:.2f}]", "res")
        training_live = 0 < lead < need
        if team_ready_stage:
            self._team_ready_idle(ctx, training_live, lead_level(ctx.emu))
        else:
            ctx.team_ready_idle = 0  # left the stage: "consecutive" restarts on re-entry
        planned = plan_step({**goals_now_all, "_starter": ctx.opts.starter, "_blocked_now": frozenset(ctx.mem.temp_blocked), "_talk_vetoed": retalk_memory.active(ctx), "_declined": set(ctx.declined_balls), "_hp": heal_gate_hp(ctx.emu), "_push_on": heal_push_on(ctx, goals_now_all, *heal_gate_hp(ctx.emu)), "_parcel_spot": parcel,
                             "_level": lead_level(ctx.emu), "_train_level": need, "_heal_trips": ctx.heal_trips,
                             "_center_intent": ctx.center_intent, "_ladders": ctx.ladders, "_cave_plan": ctx.cave_plan, "_rom_route": ctx.rom_route, "_sprites": [(pic, sx - 4, sy - 4) for pic, sy, sx in sprite_snapshot(ctx.emu)], "_mom_failed": ctx.mom_failed_until > ctx.step,
                             "_respawn": ctx.emu.read(0xD719), "_need": need_raw, "_ship": ctx.__dict__.setdefault("ship_state", {}), "_ship_plan": ctx.ship_plan, "_ckpt_steps": ctx.__dict__.setdefault("ckpt_steps", {}), "_buy_deferred": magikarp_deferral.deferred(ctx)},
                            ctx.mem.data["maps"], (m, x, y), ctx.facing)
        ctx.train_route_live = bool(team_ready_stage and training_live)
        if planned is None and team_ready_stage and training_live:
            planned = train_route.step(ctx.mem.data["maps"], (m, x, y), ctx.mem.temp_blocked, *heal_gate_hp(ctx.emu))  # no planner target: go to the grass
        # the team gate holds at the gym door: while not ready the planner's stage push must not enter
        gym = (trainers.GYM_BOSSES.get(ctx.stage_goal) or (None, None, None))[2]
        hold = nv is not None and not nv.ready and gym is not None
        if st.get("stall_hold_goal") not in (None, ctx.stage_goal):
            st.pop("stall_hold", None)  # the clock runs from first engagement until the STAGE moves on; a battle frame
            st.pop("lifted_need", None)  # (party unread, nv None) or a one-step readiness flap must never reset it
        st["stall_hold_goal"] = ctx.stage_goal
        lifted = st.get("gate_lifted") is not None
        if hold and not stall_hold_holds(st, ctx.grind.reason(st["gate_lifted"]) if lifted else "without a level gain",
                                         ctx.step, party_log.of(ctx).blackouts):  # monotonic: a win resets blackouts_row
            hold = False  # budget spent (ceiling/blackout), the hold cap, or a blackout while held: never locked out forever
            if st.get("gate_skip_logged") != ctx.stage_goal:
                st["gate_skip_logged"] = ctx.stage_goal
                why = ctx.grind.reason(st["gate_lifted"]) if lifted else f"held {STALL_HOLD_CAP} steps or a blackout"
                ctx.log(f"[team gate: grind budget spent ({why}); gym hold lifted for {ctx.stage_goal}]", "res")
        ctx.gym_hold_seen = (ctx.step, bool(hold))  # goal_talk reads this: a gym leader is only walked to when no hold is active
        if hold and st.get("gate_lifted") is not None:
            ctx.train_need = st.get("lifted_need") or ctx.train_need  # the budget stops forcing, not forbids: episodes may start
        if hold:
            self._leader_avoid(ctx, m, x, y, gym)
            if m == gym:  # inside and not ready: out before anything - frontier would explore toward the leader
                planned = self._out_step(ctx, m, x, y, gym) or self._grind_step(ctx, m, x, y, *heal_gate_hp(ctx.emu))
            elif self._enters(ctx, m, x, y, planned, gym) or self._gym_road(planned, ctx.stage_goal):
                planned = self._grind_step(ctx, m, x, y, *heal_gate_hp(ctx.emu))  # the hold owns the step: no road to the gym
        elif st.get("grinding") and need > 0:
            grind = self._grind_step(ctx, m, x, y, *heal_gate_hp(ctx.emu))
            errands = ("checkpoint", "heal", "pokecenter", "parcel", "potion", "magikarp", "mom")
            if grind is not None and (planned is None or planned[1].startswith("goal ")
                    and not any(k in planned[1].lower() for k in errands)):
                planned = grind
        if planned and planned[1].startswith("goal checkpoint"):
            ck = ctx.__dict__["ckpt_steps"]; ck[5] = ck.get(5, 0) + 1  # Vermilion is the only checkpoint town so far
        if planned and "at Mom, talking" in planned[1]:
            ctx.mom_talk_step = ctx.step; ctx.mom_talk_hp = hp_now
            ctx.slow_until = ctx.step + 12  # healing has a fade: slow down so completion is recognised
        driver = ""
        if planned and ctx.opts.par_follow:
            planned, driver = par_follow.refine(ctx, planned, [(pic, sx - 4, sy - 4) for pic, sy, sx in sprite_snapshot(ctx.emu)])
        if planned and not (ctx.explore_run and m != 0x28 and random.random() < 0.3):  # never gamble in the lab
            ep_maps = grind_episode.boundary(ctx)
            if ep_maps is not None and grind_episode.leaves_set(ctx, planned[0], ep_maps | {m}):
                return None  # the grind episode pins the run to its maps: this press would leave them
            return Decision(planned[0], "plan_goal", planned[1], driver=driver)
        return None

    @staticmethod
    def _team_need(ctx: ExplorerContext, goals: dict, need: int) -> int:
        """At the team_ready stage, level the trainee until useful ONLY while the plan's top action is the
        Magikarp candidate or the named trainee is a MAGIKARP: the lead reads min(fighter, trainee + TEAM_GAP),
        so the gate needs EVOLVE_LEVEL + TEAM_GAP to hold until Gyarados. Otherwise the catch plan does the
        team work and the stage's training level is whatever required_level gives."""
        if next((g for g in GOALS if not goals.get(g)), None) != "team_ready":
            return need
        top = next((a for a in (getattr(ctx, "team_plan", None) or []) if not a.blocked), None)
        species, slot = party_species(ctx.emu), getattr(ctx, "train_member", None)
        plan_pick = (getattr(getattr(getattr(top, "member", None), "candidate", None), "source", "")
                     in ("magikarp", "party-evolution") and getattr(top, "species", "MAGIKARP") == "MAGIKARP"
                     and MAGIKARP in species)
        named = slot is not None and 0 <= slot < len(species) and species[slot] == MAGIKARP
        return max(need, EVOLVE_LEVEL + TEAM_GAP) if plan_pick or named else need

    @staticmethod
    def _boss_gap(ctx: ExplorerContext, m: int, x: int, y: int) -> int:
        """Learned-world route steps to the stage boss's gym map (trainers.GYM_BOSSES), or NEAR_STEPS
        when the stage has no gym map or no path is known: "no data" reads as far away, never urgent."""
        gym = (trainers.GYM_BOSSES.get(ctx.stage_goal or "") or (None, None, None))[2]
        if gym is None:
            return team_plan.NEAR_STEPS
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((m, x, y), lambda n: n[0] == gym)
        return len(p) if p is not None else team_plan.NEAR_STEPS

    @staticmethod
    def _enters(ctx: ExplorerContext, m: int, x: int, y: int, planned, gym: int) -> bool:
        """True when the planned directional press takes a learned warp onto the gym map."""
        if not planned or planned[0] not in ("UP", "DOWN", "LEFT", "RIGHT"):
            return False
        dest = ctx.mem.data["maps"].get(str(m), {}).get("warps", {}).get(f"{x},{y},{planned[0]}")
        return bool(dest) and dest[0] == gym

    @staticmethod
    def _leader_avoid(ctx: ExplorerContext, m: int, x: int, y: int, gym: int) -> None:
        """On the gym map while not ready: keep the leader's (and gym trainers') sight lines temp-blocked
        for routing (trainer_route.block_sight, PR #158) so frontier cannot walk into them."""
        if m != gym:
            return
        from pokeagent.explorer import trainer_route
        from pokeagent.explorer.trainer_hooks import current_party, ledger_for
        led = ledger_for(ctx)
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        st = team_plan.of(ctx)
        key = (m, tuple(e.idx for e in led.entries(m) if e.state != "beaten"))
        quiet = st.get("avoid_key") == key   # one log line per unbeaten-set change, not per step
        st["avoid_key"] = key
        for o in trainer_route.options(led, m, (m, x, y), g, 0, current_party(ctx)):
            if o.action == "avoid":
                trainer_route.block_sight(ctx, o, lambda n, gm=gym: n[0] != gm, quiet=quiet)

    @staticmethod
    def _grind_step(ctx: ExplorerContext, m: int, x: int, y: int, hp: int, mx: int):
        """The grind decision while the pressure latch holds or the gym door blocks. ``grind_episode.start``
        returns a bool (an episode is live or it is not), never a step: True means the episode now owns the
        NEXT tick (GrindDrill is registered before PlanGoal and walks it), False means no episode could start.
        Either way this tick still needs a real press, so both outcomes fall through to the Route 24 training
        route; ``grind_episode.boundary`` (checked in ``step``) vetoes any press that would leave a live
        episode's map set."""
        grind_episode.start(ctx, "the pressure latch")
        kw = {"target": TRAIN_MAP[ctx.stage_goal]} if stage_maps.allowed(ctx.stage_goal) else {}  # pre-Brock: never Route 24
        return train_route.step(ctx.mem.data["maps"], (m, x, y), ctx.mem.temp_blocked, hp, mx, **kw)

    @staticmethod
    def _gym_road(planned, stage: str | None = None) -> bool:
        """The planner's push toward the gym map (the road north / the gym walk / the stage boss itself, e.g.
        "goal beat_misty: N steps toward it"): never taken while the hold stands. Without the stage form the
        Cerulean run walked into Misty's gym, was turned out by the hold, and walked back in (2026-11-12)."""
        why = planned[1] if planned else ""  # a stage step counts only as the learned-world walk at the boss, not a
        return why.startswith(("goal road north", "goal gym")) or bool(  # Pokecenter exit / _back_to / edge push
            stage and why.startswith(f"goal {stage}:") and "steps toward it" in why)

    @staticmethod
    def _out_step(ctx: ExplorerContext, m: int, x: int, y: int, gym: int):
        """Inside the gym while not ready: the first press of the learned route off the map (the
        heal_walk BFS shape), before anything else - frontier would explore toward the leader and
        ``_leader_avoid``'s block_sight is the only guard. None when the learned graph knows no exit."""
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        found = g._bfs_node((m, x, y), lambda n, gm=gym: n[0] != gm, 5000)
        if not found or not found[1]:
            return None
        return (found[1][0], f"team gate: not ready - {len(found[1])} steps out of the gym")

    @staticmethod
    def _team_ready_idle(ctx: ExplorerContext, training_live: bool, level: int | None = None) -> None:
        """Settle the team_ready goal early when the gate is closed or lifted so the stage has nothing to do."""
        gained = level is not None and level > getattr(ctx, "team_ready_idle_level", 0)
        if level is not None:
            ctx.team_ready_idle_level = level
        ctx.team_ready_idle = 0 if training_live or gained else ctx.team_ready_idle + 1  # a level gain is progress too
        if ctx.team_ready_idle >= GYARADOS_IDLE_CAP and not ctx.team_ready_skipped:
            ctx.team_ready_skipped = True
            ctx.log(f"[team_ready: training gate closed or lifted for {GYARADOS_IDLE_CAP} plan steps - settled for this run]", "res")

    @staticmethod
    def _budgeted(ctx: ExplorerContext, goals: dict, need: int, verdict, party=None) -> int:
        """The training level, or 0 (gate lifted) once the grind budget for this goal is spent. The
        lifted goal is published on the team-plan state so the gym hold stands down with the gate."""
        st = team_plan.of(ctx)
        stage, level = stage_goal(goals), lead_level(ctx.emu)
        if trainee_slot(ctx.emu) is None:
            level = best_level(level, party)  # the strongest slot, not a weak L4 lead (a Magikarp trainee keeps the gated measure)
        st["gate_lifted"] = None
        if stage is None:
            return need
        tr = next((g for g in GOALS if not goals.get(g)), None) == "team_ready"
        goal = "team_ready" if tr else stage  # the team_ready stage has its own budget key: it must not accrue on the next boss's
        ctx.grind = ctx.grind or GrindBudget()
        why = ctx.grind.update(goal, level=level, step=ctx.step, battles=ctx.battles, blackouts=ctx.blackouts_row,
                               training=0 < level < need and grinding_now(ctx), ceiling=level_ceiling(stage),
                               max_battles=GRIND_BATTLES_GYARADOS if tr else GRIND_BATTLES)
        if why:
            ctx.log(f"[readiness] grind budget spent for {goal}: {why}; lifting the training gate", "res")
        if ctx.grind.lifted(goal):
            st["gate_lifted"] = goal
            st["lifted_need"] = need  # a held gym still wants this level: the episode gate reads it back
            return 0
        return need
