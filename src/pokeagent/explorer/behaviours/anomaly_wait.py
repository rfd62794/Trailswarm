"""anomaly_wait: a wanderer NPC stands on the tile the agent is pressing into. Wait a few presses for it to move,
then route around its tile (temporarily blocked, never learned as a wall)."""
from __future__ import annotations

from pokeagent.explorer.anomalies import WAIT_PRESSES
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext


class AnomalyWait(BehaviourBase):
    name = "anomaly_wait"

    def applies(self, ctx: ExplorerContext) -> bool:
        mon = ctx.anomalies
        return mon is not None and mon.block is not None and not ctx.view.box and not ctx.view.battling

    def step(self, ctx: ExplorerContext) -> Decision | None:
        mon = ctx.anomalies
        blk = mon.block
        where = f"({blk.tile[0]},{blk.tile[1]})"
        if blk.waited < WAIT_PRESSES:
            blk.waited += 1
            return Decision("B", "wait_for_npc", f"NPC slot {blk.slot} blocks {where}: waiting {blk.waited}/{WAIT_PRESSES} presses for it to move")
        mon.reroute(ctx)
        return Decision("B", "reroute_npc", f"NPC slot {blk.slot} still on {where}: routing around it (tile blocked for a while, not a wall)")
