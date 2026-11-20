"""ledge_trap: never hop the one-way ledge into Cerulean's sealed pocket.

ROM: Cerulean's row 33 (x 16-23) is a ledge: a press DOWN from (x, 32) jumps to row 34, into a pocket (rows 34-35, x 16-23) whose only
exits are Route 5's sealed middle (x 6-13), closed rooms that lead straight back up. There is no way back to the town (fresh-memory
headless run from the bicycle state, 2026-11-16: ExploreBurst hopped it and 2,300 of 3,000 steps went to the pocket). The press is
replaced by B and the tile learned as a wall, so every behaviour's picker then sees it as blocked."""
from __future__ import annotations

CERULEAN, LEDGE_ROW = 0x03, 32
LEDGE_X = range(16, 24)


def veto(ctx, decision) -> str | None:
    """None to let the press through, else why it is replaced by B (the wall is learned so the pickers stop choosing it)."""
    if decision.button != "DOWN":
        return None
    m, x, y = ctx.pos()
    if m != CERULEAN or y != LEDGE_ROW or x not in LEDGE_X:
        return None
    blocked = ctx.mem.m(m)["blocked"]
    key = f"{x},{y},DOWN"
    if key not in blocked:
        blocked.append(key)
    return "the ledge below drops into Cerulean's sealed pocket (no way back): treated as a wall"
