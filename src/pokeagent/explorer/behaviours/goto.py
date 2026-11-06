"""goto: a human or Claude asked for a destination; route there over the learned world."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.world import WorldGraph


class Goto(BehaviourBase):
    name = "goto"

    def applies(self, ctx: ExplorerContext) -> bool:
        return bool(ctx.goto)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        if ctx.goto:  # a human/Claude asked for a destination: route there over the learned world
            target = tuple(ctx.goto)
            if (m, x, y) == target:
                ctx.goto = None; ctx.log(f"[arrived at {target}]", "res")
            else:
                if ctx.anomalies is not None:
                    ctx.anomalies.expire(ctx)
                g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
                p = g.path((m, x, y), lambda n: n == target)
                if p:
                    return Decision(p[0], "goto_step", f"goto {target}: {len(p)} steps left")
                if ctx.mem.temp_blocked and WorldGraph(ctx.mem.data["maps"]).path((m, x, y), lambda n: n == target):
                    return no_press("goto_wait", f"goto {target}: only route is past a wandering NPC; waiting for its tile to clear")
                ctx.goto = None; ctx.log(f"[no known route to {target}; exploring instead]", "res")
        return None

    def done(self, ctx: ExplorerContext) -> bool:
        return not ctx.goto

    def failed(self, ctx: ExplorerContext) -> bool:
        return False  # an unreachable target clears itself and falls back to exploring (logged)
