"""frontier: explore. New-map bursts, then the default rule: least-visited neighbour or the nearest frontier tile."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_hp


class ExploreBurst(BehaviourBase):
    """A map NEW TO MEMORY (or a new item) earns a burst of maximal exploration before plans resume."""

    name = "explore_burst"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # the new-map bookkeeping must see every step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        tm_now = ctx.view.tm
        hp_now, mx_now = party_hp(ctx.emu)
        ctx.goals()
        if ctx.known_maps_at_start is None:
            ctx.known_maps_at_start = {int(k) for k in ctx.mem.data["maps"] if len(ctx.mem.data["maps"][k].get("visited", {})) >= 5}
        if m not in ctx.burst_maps:  # a map NEW TO MEMORY: maximal exploration before plans resume
            ctx.burst_maps.add(m)
            if m not in ctx.known_maps_at_start:
                ctx.explore_burst = max(ctx.explore_burst, 120)
                ctx.log(f"[new map 0x{m:02X}: exploration burst, 120 steps before plans resume]", "res")
        if ctx.explore_burst > 0 and not (mx_now and hp_now / mx_now < 0.4):
            ctx.explore_burst -= 1
            name, why = ctx.mem.choose(m, x, y, ctx.facing, tm_now, ctx.emu.read(0xD367), grass="neutral")
            return Decision(name, "explore_burst", f"exploring a new discovery ({ctx.explore_burst} left): {why}")
        return None

    def done(self, ctx: ExplorerContext) -> bool:
        return ctx.explore_burst <= 0


class Frontier(BehaviourBase):
    """The fallback: memory-guided exploration (grass seeking when training, avoiding it when weak)."""

    name = "frontier"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        tm_now = ctx.view.tm
        hp_now, mx_now = party_hp(ctx.emu)
        goals_now_all = ctx.goals()
        weak = mx_now and hp_now / mx_now < 0.4
        training = goals_now_all.get("won_battle") and goals_now_all.get("to_route1") and 0 < ctx.emu.read(0xD18C) < 8 and not weak
        name, why = ctx.mem.choose(m, x, y, ctx.facing, tm_now, ctx.emu.read(0xD367),
                               avoid_maps={0x00} if (training and m == 0x0C) else None,
                               grass="seek" if training else "avoid" if weak else "neutral")
        return Decision(name, "frontier", why)
