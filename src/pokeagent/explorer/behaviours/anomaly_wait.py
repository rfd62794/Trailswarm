"""anomaly_wait: a wanderer NPC stands on the tile the agent is pressing into. Wait a short while (no button pressed)
for it to move, then route around its tile (temporarily blocked, never learned as a wall)."""
from __future__ import annotations

from pokeagent.explorer.anomalies import WAIT_FRAMES
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext


class AnomalyWait(BehaviourBase):
    name = "anomaly_wait"

    def applies(self, ctx: ExplorerContext) -> bool:
        mon = ctx.anomalies
        return mon is not None and mon.block is not None and not ctx.view.box and not ctx.view.battling

    def step(self, ctx: ExplorerContext) -> Decision | None:
        mon = ctx.anomalies
        blk = mon.check_block(ctx)
        if blk is None:
            return None  # it moved on its own: carry on
        where = f"({blk.tile[0]},{blk.tile[1]})"
        waited = ctx.frame - blk.since
        if waited < WAIT_FRAMES:
            return no_press("wait_for_npc", f"NPC slot {blk.slot} blocks {where}: waiting for it to move ({waited}/{WAIT_FRAMES} frames)")
        mon.reroute(ctx)
        return no_press("reroute_npc", f"NPC slot {blk.slot} still on {where}: routing around it (tile blocked for a while, not a wall)")
