"""trainer_hunt: walk to the next trainer the readiness sim says the party beats.

Sibling of learner_hunt.py: trainer_route.options() ranks the current map's unbeaten/unknown ROM
placements; the nearest ``engage`` target's APPROACH tile is walked over the learned graph, and an
``avoid`` trainer's sight line is temp-blocked while a route survives (never the only route). Gated
like learner_hunt - not battling, no box, no procedure, no goto wanting a tile - plus a per-run step
cap, so it never blocks the route. It does not drive presses past its own walk decision: plan_goal and
the planners keep their say.
"""
from __future__ import annotations

from dataclasses import replace

from pokeagent.explorer import trainer_ledger, trainer_route
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.world import WorldGraph
from pokeagent.knowledge.party import our_party
from pokeagent.ramstructs import read_party

TRAINER_HUNT_STEP_CAP = 2000  # per-run steps spent hunting; untuned first value (it never blocks the route)


class TrainerHunt(BehaviourBase):
    name = "trainer_hunt"

    def __init__(self) -> None:
        self._announced: trainer_route.TrainerOption | None = None  # last next_target logged (once per target)

    def applies(self, ctx: ExplorerContext) -> bool:
        if (ctx.trainer_hunt_steps > TRAINER_HUNT_STEP_CAP or ctx.view.battling or ctx.view.box
                or ctx.proc is not None or ctx.goto):
            return False
        led = trainer_ledger.ledger_for(ctx)
        return any(e.state != "beaten" for e in led.entries(ctx.view.m))

    def _route(self, ctx: ExplorerContext, g: WorldGraph):
        """(route_steps, goal_fn): the current destination = an explicit goto else the committed
        frontier tile; (0, None) when nothing is being routed to."""
        dest = tuple(ctx.goto) if ctx.goto else ctx.frontier_target
        if not dest:
            return 0, None
        p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n == dest)
        return (len(p) if p is not None else 0), (lambda n, d=dest: n == d)

    def _party(self, ctx: ExplorerContext):
        """our_party() with each member's HP replaced by its CURRENT hp: a hurt party sims worse."""
        try:
            cur = [m.hp for m in read_party(ctx.emu)]
            party = our_party(ctx.emu)
            return [replace(c, hp=cur[i]) for i, c in enumerate(party) if i < len(cur)]
        except Exception:  # noqa: BLE001
            return []

    def step(self, ctx: ExplorerContext) -> Decision | None:
        ctx.trainer_hunt_steps += 1
        led = trainer_ledger.ledger_for(ctx)
        player = (ctx.view.m, ctx.view.x, ctx.view.y)
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        route_steps, goal_fn = self._route(ctx, g)
        opts = trainer_route.options(led, ctx.view.m, player, g, route_steps, self._party(ctx))
        for o in opts:
            if o.action == "avoid" and goal_fn is not None:
                trainer_route.block_sight(ctx, o, goal_fn)  # routing-only; downgrades to engage-forced alone
        t = trainer_route.next_target(opts)
        ctx.trainer_target = None
        if t is None:
            return None
        goal = (ctx.view.m, *trainer_route.approach_tile(t.entry, player))
        ctx.trainer_target = goal  # the exploration/goto machinery may read it; it does not drive the press
        if t is not self._announced:
            self._announced = t
            margin = f"{t.margin:+.2f}" if t.margin is not None else "n/a"
            ctx.log(f"[trainer_route: next target {t.entry.cls} p{t.entry.party} ({t.entry.x},{t.entry.y}): "
                    f"margin {margin}, {t.steps} steps]", "res")
        p = g.path(player, lambda n: n == goal)
        if not p:
            return None
        return Decision(p[0], "trainer_hunt_walk",
                        f"trainer_hunt: {len(p)} steps to {t.entry.cls} p{t.entry.party} ({goal[1]},{goal[2]})")
