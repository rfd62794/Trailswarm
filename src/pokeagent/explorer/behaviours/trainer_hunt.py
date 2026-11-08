"""trainer_hunt: walk to the next trainer the readiness sim says the party beats.

Sibling of learner_hunt.py: trainer_route.options() ranks the current map's unbeaten/unknown ROM
placements; the nearest ``engage`` target's APPROACH tile is walked over the learned graph, and an
``avoid`` trainer's sight line is temp-blocked by trainer_hooks.avoid_pass (any destination, not only
when this behaviour runs) while a route survives (never the only route). Gated
like learner_hunt - not battling, no box, no procedure, no goto wanting a tile - plus a per-run step
cap, so it never blocks the route. It does not drive presses past its own walk decision: plan_goal and
the planners keep their say.
"""
from __future__ import annotations

from pokeagent.explorer import grind_episode, trainer_ledger, trainer_route
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.trainer_hooks import current_party
from pokeagent.explorer.world import WorldGraph

TRAINER_HUNT_STEP_CAP = 2000  # per-run steps spent hunting; untuned first value (it never blocks the route)


class TrainerHunt(BehaviourBase):
    name = "trainer_hunt"

    def __init__(self) -> None:
        self._announced: trainer_route.TrainerOption | None = None  # last next_target logged (once per target)

    def applies(self, ctx: ExplorerContext) -> bool:
        if (ctx.trainer_hunt_steps > TRAINER_HUNT_STEP_CAP or ctx.view.battling or ctx.view.box
                or ctx.proc is not None or ctx.goto or grind_episode.active(ctx) is not None):
            return False
        led = trainer_ledger.ledger_for(ctx)
        return any(e.state != "beaten" for e in led.entries(ctx.view.m))

    def _route_steps(self, ctx: ExplorerContext, g: WorldGraph) -> int:
        """Path steps to the committed frontier tile (0 when none): the segment route the options compare to."""
        dest = ctx.frontier_target
        p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n == dest) if dest else None
        return len(p) if p is not None else 0

    def step(self, ctx: ExplorerContext) -> Decision | None:
        led = trainer_ledger.ledger_for(ctx)
        player = (ctx.view.m, ctx.view.x, ctx.view.y)
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        opts = trainer_route.options(led, ctx.view.m, player, g, self._route_steps(ctx, g), current_party(ctx))
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
        ctx.trainer_hunt_steps += 1  # only steps that acted count toward the cap
        return Decision(p[0], "trainer_hunt_walk",
                        f"trainer_hunt: {len(p)} steps to {t.entry.cls} p{t.entry.party} ({goal[1]},{goal[2]})")
