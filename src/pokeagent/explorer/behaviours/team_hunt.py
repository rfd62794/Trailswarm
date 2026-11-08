"""team_hunt: walk to the map of the catch plan's best action, then let frontier seek its grass.

Sibling of learner_hunt.py (same applies/step shape over the learned world graph). The plan
(knowledge.catch_plan.plan_catches) ranks "catch species S on map M" actions by value per step - boss
contribution, Pokedex progress and the catcher role, minus training cost. When the best doable action is on
another reachable map within the detour budget this behaviour walks the learned graph to it; on the target map
it sets ``ctx.hunt_grass`` so frontier seeks grass and the existing Catch behaviour throws at a wanted species.
The plan is refreshed at most every PLAN_REFRESH_STEPS steps or when the cache key (map, party size, owned
count, goal set) changes. It never blocks the route: a per-run step cap settles it, and it yields to every gate
the no-blackout rules impose (HP, potion floor, balls, boss segments, dungeons, ships).
"""
from __future__ import annotations

from collections import deque

from pokeagent.explorer import grind_episode
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.economy import heal_items
from pokeagent.explorer.economy.floor import FLOOR_MIN
from pokeagent.explorer.perceive import lead_level, party_hp
from pokeagent.explorer.catch_list import dex_owned_count
from pokeagent.explorer.world import DUNGEON_MAPS, SHIP_MAPS, WorldGraph
from pokeagent.goals import GOALS, bag_contents
from pokeagent.knowledge import trainers
from pokeagent.knowledge.catch_plan import TEAM_SIZE, map_prior_xp, plan_catches
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party
from pokeagent.knowledge.team_value import BOSS_HORIZON, DEX_GATES
from pokeagent.explorer.training import BOSS_LABEL, TRAIN_LEVEL_BY_GOAL
from pokeagent.magikarp import magikarp_stats
from pokeagent.ramworld import read_money
from pokeagent.ramstructs import read_party_count

POKE_BALL = 0x04
FAR = 1_000_000            # the learned graph cannot reach the map: treat it as farthest, not impossible
TEAM_HUNT_BUDGET = 400     # max detour in path steps to walk for a catch action; untuned
TEAM_HUNT_STEP_CAP = 3000  # per-run steps spent hunting, after which it stops for the run (it never blocks); untuned
TEAM_HUNT_MIN_HP = 0.6     # party_hp fraction needed to hunt (no-blackout run); untuned
PLAN_REFRESH_STEPS = 50    # rebuild the catch plan at most this often (steps); untuned
DEX_OWNED = 0xD2F7         # wPokedexOwned


class TeamHunt(BehaviourBase):
    name = "team_hunt"

    def __init__(self) -> None:
        self._armed = False                  # we set ctx.hunt_grass (only then may we clear and re-arm it)
        self._planned_at = -PLAN_REFRESH_STEPS
        self._plan_key: tuple | None = None
        self._announced: tuple | None = None  # the last target logged (once per target)

    def applies(self, ctx: ExplorerContext) -> bool:
        goals = ctx.goals()
        # re-arm ctx.hunt_grass ONLY when we set it: learner_hunt runs first and a True from it must survive.
        learner_live = bool(goals.get("hm01_cut")) and not goals.get("cut_learner") and not ctx.cut_learner_skipped
        if self._armed:
            if not (learner_live and ctx.hunt_grass):
                ctx.hunt_grass = False
            self._armed = False
        ok = (ctx.team_hunt_steps <= TEAM_HUNT_STEP_CAP and not ctx.view.battling and not ctx.view.box
              and ctx.proc is None and ctx.center_intent is None and grind_episode.active(ctx) is None
              and not (next((g for g in GOALS if not goals.get(g)), "") or "").startswith(("beat_", "rival_"))
              and ctx.view.m not in SHIP_MAPS and ctx.view.m not in DUNGEON_MAPS and ctx.blackouts_row == 0)
        if ok:
            hp, mx = party_hp(ctx.emu)
            bag = bag_contents(ctx.emu)
            ok = (bool(mx) and hp / mx >= TEAM_HUNT_MIN_HP and heal_items.heal_count(bag) >= FLOOR_MIN
                  and bag.get(POKE_BALL, 0) >= 1 and read_party_count(ctx.emu) < TEAM_SIZE)
        if not ok:
            ctx.team_wants = {}
            ctx.team_plan = []
            self._plan_key = None  # a gate blip must not leave the plan empty until the refresh interval
            return False
        self._refresh(ctx, goals, bag)
        return bool(ctx.team_plan)

    # --- the plan --------------------------------------------------------------------------------------------

    def _graph_dist(self, ctx: ExplorerContext, target_map: int) -> float:
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n[0] == target_map)
        return len(p) if p is not None else FAR

    def _bosses(self, ctx: ExplorerContext, goals: dict, party) -> list:
        """[(label, [(level, species)])] for the next BOSS_HORIZON boss goals not yet met."""
        names = [c.name for c in party]
        out = []
        for g in GOALS:
            if len(out) >= BOSS_HORIZON:
                break
            if g not in TRAIN_LEVEL_BY_GOAL or goals.get(g):
                continue
            mons = trainers.boss_party(g, starter_names=names) or (
                trainers.strongest_on_mt_moon() if g == "to_mt_moon" else [])
            if mons:
                out.append((BOSS_LABEL.get(g, g), mons))
        return out

    def _owned_species(self, ctx: ExplorerContext) -> set:
        out = set()
        for d, row in table(None, "species_by_dex").items():
            dex = int(d) if str(d).isdigit() else 0
            if dex > 0 and ctx.emu.read(DEX_OWNED + (dex - 1) // 8) >> ((dex - 1) % 8) & 1:
                out.add(row.get("name"))
        return out

    def _refresh(self, ctx: ExplorerContext, goals: dict, bag: dict) -> None:
        owned_count = dex_owned_count(ctx.emu)
        key = (ctx.view.m, read_party_count(ctx.emu), owned_count, frozenset(g for g, v in goals.items() if v))
        if key == self._plan_key and ctx.step - self._planned_at < PLAN_REFRESH_STEPS:
            self._publish_wants(ctx, owned_count)
            return
        self._plan_key, self._planned_at = key, ctx.step
        party = our_party(ctx.emu)
        wild = table(None, "wild_by_map")
        base_exp = {r["name"]: int(r.get("base_exp", 0) or 0) for r in table(None, "species_by_dex").values()}
        ctx.team_plan = plan_catches(
            party, ctx.view.m, goals, read_money(ctx.emu), bag.get(POKE_BALL, 0), owned_count,
            self._bosses(ctx, goals, party), wild, ctx.mem.data["maps"], lead_level(ctx.emu),
            distance=lambda _a, b: self._graph_dist(ctx, b),
            magikarp_level=(magikarp_stats(ctx.emu) or {}).get("level"),
            xp_for_map=lambda m: map_prior_xp(wild.get(m) or wild.get(str(m)) or {}, base_exp),
            owned_species=self._owned_species(ctx), kb=None)
        ctx.team_plan = [a for a in ctx.team_plan if a.detour < FAR]
        self._publish_wants(ctx, owned_count)

    def _route_maps(self, ctx: ExplorerContext, target: int) -> set:
        """Map ids on the learned-graph route to ``target`` (the current map when there is no route)."""
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        start, prev, q = (ctx.view.m, ctx.view.x, ctx.view.y), {}, deque([(ctx.view.m, ctx.view.x, ctx.view.y)])
        prev[start] = None
        while q:
            cur = q.popleft()
            if cur[0] == target:
                out = set()
                while cur is not None:
                    out.add(cur[0]); cur = prev[cur]
                return out
            for nxt, _btn in g.neighbours(cur):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        return {ctx.view.m}

    @staticmethod
    def _reason(a, owned_count: int) -> str:
        if a.member.contributes:
            return f"planned: value {a.value:.1f} (contributes to {', '.join(a.member.contributes)})"
        gate = next((g for g in DEX_GATES if g > owned_count), None)
        return f"planned: new species {owned_count + 1}/{gate or 'max'} toward the Pokedex gate, {a.steps:.0f} steps"

    def _publish_wants(self, ctx: ExplorerContext, owned_count: int) -> None:
        """team_wants holds only actions on the current map or on the route to the top action."""
        top = next((a for a in ctx.team_plan if not a.blocked), None)
        route = self._route_maps(ctx, top.map) if top and top.map else {ctx.view.m}
        ctx.team_wants = {a.species: self._reason(a, owned_count) for a in ctx.team_plan if a.map in route}

    # --- the walk --------------------------------------------------------------------------------------------

    def step(self, ctx: ExplorerContext) -> Decision | None:
        top = next((a for a in ctx.team_plan if not a.blocked), None)
        if top is None:
            return None
        ctx.team_hunt_steps += 1  # counted only when a plan is live and the gates passed
        if top.map and (top.map, top.species) != self._announced:
            self._announced = (top.map, top.species)
            ctx.log(f"[team_hunt: {top.species} on {top.name} (0x{top.map:02X}), L{top.levels[0]}-{top.levels[1]}, "
                    f"{top.chance * 100:.0f}%/encounter, value {top.value:.1f}, cost {top.steps:.0f} steps]", "res")
        if top.map == 0 or top.map == ctx.view.m:
            if any(not a.blocked and a.map == ctx.view.m for a in ctx.team_plan):
                ctx.hunt_grass = self._armed = True
            return None  # on the grass map (or a train-the-party action): frontier/Catch do the rest
        if top.detour > TEAM_HUNT_BUDGET:
            return None
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n[0] == top.map)
        if not p:
            return None
        return Decision(p[0], "team_hunt_walk", f"team_hunt: {len(p)} steps to {top.species} on {top.name}")
