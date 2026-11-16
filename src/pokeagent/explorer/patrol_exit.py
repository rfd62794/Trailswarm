"""patrol_exit: an interior map with nothing left to explore is left by a learned warp, never patrolled.

The explorer walked into Cerulean's Bike Shop looking for Route 5 and patrolled it for 1,250 steps (live marathon 2026-11-15): its
warp was learned (it walked in), so door_exit did not fire, and no frontier was left. When the current stage's target is on ANOTHER
map, the path over the LEARNED world to the nearest other map is taken instead. Not fired: overworld maps, caves (Mt Moon floors
flip by design), ship maps, Pokecenters (a deliberate stop), a set center intent, a stage with no map target, or a map already
left EXIT_CAP times in the last EXIT_WINDOW steps (no ping-pong with an explorer that walks back in)."""
from __future__ import annotations

from pokeagent.explorer.world import DUNGEON_MAPS, POKECENTER_MAPS, SHIP_MAPS, WorldGraph
from pokeagent.ramworld import read_map_header

OVERWORLD_TILESET = 0
EXIT_CAP, EXIT_WINDOW = 3, 600


def _skip_map(m: int) -> bool:
    return m in DUNGEON_MAPS or m in SHIP_MAPS or m in POKECENTER_MAPS


def _target_elsewhere(ctx, m: int, x: int, y: int) -> bool:
    from pokeagent.explorer.planner_east import TARGETS  # late: planner_east pulls in the planners
    target = TARGETS.get(getattr(ctx, "stage_goal", None))
    return target is not None and not target((m, x, y))


def exit_step(ctx, m: int, x: int, y: int) -> tuple[str, str] | None:
    """(button, why) along the learned route out of interior map ``m``, or None (see the module docstring for when)."""
    if _skip_map(m) or getattr(ctx, "center_intent", None) or not _target_elsewhere(ctx, m, x, y):
        return None
    try:
        if read_map_header(ctx.emu).tileset == OVERWORLD_TILESET:
            return None
    except Exception:  # noqa: BLE001  fake / unreadable header: no interior knowledge
        return None
    g = WorldGraph(ctx.mem.data["maps"]); g.blocked_now = frozenset(ctx.mem.temp_blocked)
    p = g.path((m, x, y), lambda n: n[0] != m)
    if not p:
        return None
    step = getattr(ctx, "step", 0)
    log = [s for s in ctx.__dict__.setdefault("patrol_exits", {}).get(m, []) if step - s < EXIT_WINDOW]
    if len(log) >= EXIT_CAP:
        return None
    if len(p) == 1:
        log.append(step)  # the last press: the exit itself
    ctx.patrol_exits[m] = log
    return p[0], f"nothing left to explore on interior map 0x{m:02X}: {len(p)} steps to its learned exit"
