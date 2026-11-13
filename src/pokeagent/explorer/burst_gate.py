"""burst_gate: when does receiving an item earn an exploration burst?

Only a genuinely NEW item found by exploring does. Never right after a trainer battle (the after_victory decision
owns the next move: Route 24's nugget stalled ~170 steps on a 60-step burst that outranked the planner, 2026-11-12),
while an after_victory push is pending, or when a person handed it over (a giver is not a discovery)."""
from __future__ import annotations

from pokeagent.explorer.perceive import DIRS
from pokeagent.explorer.procedures.state import of as proc_state

TRAINER_WIN_WINDOW = 150  # steps after a trainer win in which a gain is part of that fight's aftermath


def burst_allowed(ctx, item: int, bag_pre: dict, name: str, box_before: bool, before: tuple) -> bool:
    if item in bag_pre:
        return False  # more of an item we already hold: nothing new
    if proc_state(ctx).get("twins", 0) > 0:
        return False  # an after_victory decision is still pending
    won_at = ctx.__dict__.get("trainer_win_step")
    if won_at is not None and ctx.step - won_at <= TRAINER_WIN_WINDOW:
        return False
    if name in ("A", "B") and box_before and ctx.facing in DIRS:
        dx, dy = DIRS[ctx.facing]
        if ctx.mem.npc_at(before[0], before[1] + dx, before[2] + dy) is not None:
            return False  # handed over by the person in front
    return True
