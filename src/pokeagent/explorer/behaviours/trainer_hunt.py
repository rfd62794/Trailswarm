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
from pokeagent.explorer.perceive import DIRS
from pokeagent.explorer.trainer_hooks import current_party
from pokeagent.explorer.world import WorldGraph

CLOSE_IN_CAP = 12  # presses spent closing in on / talking to ONE trainer after reaching its approach tile
TRAINER_HUNT_STEP_CAP = 2000  # per-run steps spent hunting; untuned first value (it never blocks the route)


class TrainerHunt(BehaviourBase):
    name = "trainer_hunt"

    def __init__(self) -> None:
        self._announced: trainer_route.TrainerOption | None = None  # last next_target logged (once per target)
        self._close_in: dict[tuple[int, int], int] = {}  # (map, idx) -> presses spent closing in after arriving

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
        opts = [o for o in opts if self._close_in.get((o.entry.map, o.entry.idx), 0) < CLOSE_IN_CAP]  # gave up on it
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
        if self._close_in.get((t.entry.map, t.entry.idx), 0) > 0:
            return self._close_in_step(ctx, t, player)  # already arrived once: stay on it, do not walk back out
        p = g.path(player, lambda n: n == goal)
        if p == [] and player == goal:
            return self._close_in_step(ctx, t, player)
        if not p:
            return None
        ctx.trainer_hunt_steps += 1  # only steps that acted count toward the cap
        return Decision(p[0], "trainer_hunt_walk",
                        f"trainer_hunt: {len(p)} steps to {t.entry.cls} p{t.entry.party} ({goal[1]},{goal[2]})")


    def _close_in_step(self, ctx: ExplorerContext, t: trainer_route.TrainerOption, player) -> Decision | None:
        """Standing on the approach tile and the trainer has not sighted us (already beaten in this save, or
        facing away): walk up to it, face it and press A, so a fight starts or the ledger learns talk_no_battle.
        Returning None here (the old behaviour) left the frontier to walk away and the hunt to walk back, forever
        (Route 25 LASS, 2026-11-15, ~2500 steps). CLOSE_IN_CAP bounds it; past it the trainer is dropped."""
        key = (t.entry.map, t.entry.idx)
        n = self._close_in.get(key, 0)
        self._close_in[key] = n + 1
        dx, dy = t.entry.x - player[1], t.entry.y - player[2]
        if abs(dx) + abs(dy) == 1:
            want = next(k for k, v in DIRS.items() if v == (dx, dy))
            if ctx.facing == want:
                return Decision("A", "trainer_hunt_talk", f"trainer_hunt: talking to {t.entry.cls} p{t.entry.party}")
            return Decision(want, "trainer_hunt_face", f"trainer_hunt: facing {t.entry.cls} p{t.entry.party}")
        if abs(dx) >= abs(dy):
            step_dir = (1 if dx > 0 else -1, 0)
        else:
            step_dir = (0, 1 if dy > 0 else -1)
        want = next(k for k, v in DIRS.items() if v == step_dir)
        return Decision(want, "trainer_hunt_close_in", f"trainer_hunt: closing in on {t.entry.cls} p{t.entry.party}")
