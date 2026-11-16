"""patrol_exit: an interior map with nothing left to explore is left by a learned warp, never patrolled.

The explorer walked into Cerulean's Bike Shop looking for Route 5 and patrolled it for 1,250 steps (live marathon 2026-11-15): its
warp was learned (it walked in), so door_exit did not fire, and no frontier was left. An interior (non-overworld tileset) map with no
frontier has nothing for the pending goal, so the path over the LEARNED world to the nearest other map is taken instead."""
from __future__ import annotations

from pokeagent.explorer.world import WorldGraph
from pokeagent.ramworld import read_map_header

OVERWORLD_TILESET = 0


def exit_step(ctx, m: int, x: int, y: int) -> tuple[str, str] | None:
    """(button, why) along the learned route out of interior map ``m``, or None (overworld, unreadable header, no learned exit)."""
    try:
        if read_map_header(ctx.emu).tileset == OVERWORLD_TILESET:
            return None
    except Exception:  # noqa: BLE001  fake / unreadable header: no interior knowledge
        return None
    g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
    p = g.path((m, x, y), lambda n: n[0] != m)
    return (p[0], f"nothing left to explore on interior map 0x{m:02X}: {len(p)} steps to its learned exit") if p else None
