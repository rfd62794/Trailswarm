"""learner_hunt: while cut_learner is unmet, walk to the grass where a Cut-capable wild species lives.

Sibling of goal_talk.py (same applies/step shape over the learned world graph). While ``hm01_cut`` is met and
``cut_learner`` is not - a Squirtle-run party holds HM01 with nobody to teach - it picks the nearest grass map
whose table holds a Cut-compatible species (catch_list.catch_target_map; Route 6's Oddish for Red from Vermilion),
walks the learned graph to it, then sets ``ctx.hunt_grass`` so frontier seeks grass. The existing Catch behaviour
does the rest: catch_wanted already answers "can learn CUT" for that species while a later goal needs the tag.
When the Poke Ball count is 0 nothing new happens - the existing restock logic buys balls; no shopping is added.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.catch_list import catch_target_map, hm_table
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.world import WorldGraph
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party

FAR = 1_000_000  # the learned graph cannot reach the map: treat it as farthest, not impossible


class LearnerHunt(BehaviourBase):
    name = "learner_hunt"

    def applies(self, ctx: ExplorerContext) -> bool:
        ctx.hunt_grass = False  # re-armed in step on the target map; self-heals the step the goal settles
        g = ctx.goals()
        return bool(g.get("hm01_cut")) and not g.get("cut_learner") and not ctx.cut_learner_skipped \
            and not ctx.view.battling and not ctx.view.box and ctx.proc is None

    def _graph_dist(self, ctx: ExplorerContext, target_map: int) -> float:
        """Graph-path length from where we stand to any tile of ``target_map`` (pick_target's distance)."""
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n[0] == target_map)
        return len(p) if p is not None else FAR

    def _pick(self, ctx: ExplorerContext):
        return catch_target_map(
            ctx.goals(), our_party(ctx.emu), hm_table(), table(None, "wild_by_map"),
            ctx.view.m, ctx.mem.data["maps"], distance=lambda _a, b: self._graph_dist(ctx, b))

    def _announce(self, ctx: ExplorerContext, t) -> None:
        ctx.log(f"[cut_learner: {t.species} on {t.name} (0x{t.map:02X}), L{t.levels[0]}-{t.levels[1]}, "
                f"{t.chance * 100:.0f}%/encounter]", "res")

    def step(self, ctx: ExplorerContext) -> Decision | None:
        t = ctx.learner_target
        if t is None:
            t = ctx.learner_target = self._pick(ctx)
            if t is None:
                return None  # no candidate the tables know: exploration goes on (the step cap will settle the goal)
            self._announce(ctx, t)
        v = ctx.view
        if v.m == t.map:
            ctx.hunt_grass = True
            return None  # on the grass map: frontier seeks grass and Catch throws at a wanted learner
        g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path((v.m, v.x, v.y), lambda n: n[0] == t.map)
        if not p:
            # No known route: the cached pick may be a poor early one. Re-pick; a reachable candidate replaces it.
            t2 = self._pick(ctx)
            if t2 is None or t2.map == t.map:
                return None  # nothing better known: exploration finds a route
            t = ctx.learner_target = t2
            self._announce(ctx, t)
            p = g.path((v.m, v.x, v.y), lambda n: n[0] == t.map)
            if not p:
                return None
        return Decision(p[0], "learner_hunt_walk", f"cut_learner: {len(p)} steps to {t.species} grass on {t.name}")
