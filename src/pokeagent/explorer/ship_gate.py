"""S.S. Anne gate: be ready BEFORE boarding, and find the way back to Vermilion after a blackout.

Why (2026-11-06): the captain segment starts aboard with an L12 lead. The bow sailor's Machop beats it, the blackout respawns the
agent in Cerulean (wLastBlackoutMap stayed 3), no plan led back to the ship (the learned graph is in pieces) and the frontier
wandered Cerulean and its Mart for the rest of the run. Rules, all pure over the goals dict the planner already builds:
  * walk_off_step: aboard and still short of the stage's training level -> leave the ship once per run through the ROM warps back
    to the dock and Vermilion (the ship is docked until the captain gives Cut); the Vermilion checkpoint then heals, which moves
    the respawn point;
  * ready_gate: short of the level in Vermilion -> go to Route 6's grass instead of boarding (on Route 6/11 exploration grinds);
  * route_back_step: a ship stage and the agent in Cerulean / Route 5 / the Underground Path / Route 6 -> walk to Vermilion over
    the learned world, falling back to the learned warp of the current map that leads to the next map of that chain.
State lives in goals["_ship"] (a ctx-owned dict): {"off": 0 untouched | 1 walking off | 2 done, "steps": walk-off presses}.
"""
from __future__ import annotations

from pokeagent.explorer.world import SHIP_MAPS, WorldGraph
from pokeagent.goals import GOALS

VERMILION, ROUTE6, DOCK = 0x05, 0x11, 0x5E
OUTSIDE = 255  # a ROM warp destination "the map you came from": the dock's exit to Vermilion
SHIP_STAGES = ("to_ss_anne", "rival_ss_anne", "ss_anne_captain")
# Cerulean -> Route 5 -> Route 5 gate (0x47) -> Underground Path (0x77) -> Route 6 gate (0x4A) -> Route 6 -> Vermilion
CHAIN = {0x03: 0x10, 0x10: 0x47, 0x47: 0x77, 0x77: 0x4A, 0x4A: 0x11, 0x11: VERMILION}
BACK_MAPS = frozenset(CHAIN)
_grids = False      # lazy legs.grid.rom_grids(): False = not tried, None = no ROM
WALK_OFF_CAP = 400   # presses of the walk-off before it is given up for the run


def _on(m: int):
    return lambda n: n[0] == m


def under_level(goals: dict) -> bool:
    """The lead is below the stage's training level. ``_need`` is the level before the per-map gate (the ship's gate is 0)."""
    level, need = goals.get("_level", 0), goals.get("_need", goals.get("_train_level", 0))
    return 0 < level < need


def weak(goals: dict) -> bool:
    """The fighter is below half HP: boarding (or staying aboard) with it is how a 6/78 lead lost to the bow sailor."""
    hp, mx = goals.get("_hp", (0, 0))
    return mx > 0 and hp / mx < 0.5


def ship_stage(goals: dict) -> bool:
    """The next unmet campaign goal is a ship stage (the Vermilion Pokecenter rule uses it without the planner's ladder)."""
    return next((s for s in GOALS[GOALS.index("to_route3"):] if not goals.get(s)), None) in SHIP_STAGES


def unfit(goals: dict) -> bool:
    return under_level(goals) or weak(goals)


def left_ship(goals: dict, pos: tuple) -> None:
    """A walk-off in progress ends when the agent is off the ship."""
    st = goals.get("_ship")
    if st is not None and st.get("off") == 1 and pos[0] not in SHIP_MAPS:
        st["off"] = 2


def walk_off_step(goals: dict, pos: tuple, maps: dict | None = None) -> tuple[str, str] | None:
    """Aboard and under-level: the ROM route back to the dock and out to Vermilion, once per run."""
    st, plan = goals.get("_ship"), goals.get("_ship_plan")
    if st is None or plan is None or pos[0] not in SHIP_MAPS:
        return None
    if st.get("off") == 2 or (st.get("off", 0) == 0 and not unfit(goals)):
        return None
    st["off"], st["steps"] = 1, st.get("steps", 0) + 1
    if st["steps"] > WALK_OFF_CAP:
        st["off"] = 2
        return None
    buttons = plan(pos, plan.warp_tiles(DOCK, OUTSIDE))
    if not buttons:
        st["off"] = 2  # no route (unreadable ROM): stay aboard rather than loop
        return None
    # An edge warp (the bow's two tiles) only fires on a press toward the edge, so the ROM hop onto its tile lands us ON it and the
    # next plan oscillates (DOWN/UP forever): when we stand on a LEARNED warp tile whose map lies on the route, press its direction.
    on_route = {c[0] for c in plan.follow(pos, buttons)}
    for key, dest in (maps or {}).get(str(pos[0]), {}).get("warps", {}).items():
        x, y, d = key.split(",")
        if (int(x), int(y)) == pos[1:] and dest[0] in on_route and dest[0] != pos[0]:
            return d, f"goal walk-off: taking the learned warp {key} to map 0x{dest[0]:02X}"
    return buttons[0], f"goal walk-off: {'weak' if weak(goals) else 'under-level'} (L{goals.get('_level')}, need L{goals.get('_need')}, HP {goals.get('_hp')}), {len(buttons)} steps off the ship to Vermilion"


def ready_gate(g: WorldGraph, goals: dict, pos: tuple) -> tuple[str, str] | None:
    """Not ready for the ship: in Vermilion go grind on Route 6 (on Route 6 / 11 None lets exploration seek the grass)."""
    if not under_level(goals) or pos[0] != VERMILION:
        return None
    p = g.path(pos, _on(ROUTE6))
    if p:
        return p[0], f"goal train: {len(p)} steps to Route 6's grass (under-level for the ship: L{goals.get('_level')} < L{goals.get('_need')})"
    return None


def route_back_step(g: WorldGraph, goals: dict, pos: tuple, grid_get=None) -> tuple[str, str] | None:
    """Ship ahead again after a blackout: walk from Cerulean / Route 5 / the Underground Path / Route 6 to Vermilion."""
    if pos[0] not in BACK_MAPS:
        return None
    p = g.path(pos, _on(VERMILION))
    if p:
        return p[0], f"goal back to the ship: {len(p)} steps to Vermilion over the learned world"
    nxt = CHAIN[pos[0]]  # the learned world is in pieces: head for the warp that leads to the next map of the chain
    for key, dest in g.maps.get(str(pos[0]), {}).get("warps", {}).items():
        x, y, d = key.split(",")
        if dest[0] != nxt:
            continue
        tile = (pos[0], int(x), int(y))
        if pos == tile:
            return d, f"goal back to the ship: taking the warp to map 0x{nxt:02X}"
        q = g.path(pos, lambda n, tile=tile: n == tile)
        if q:
            return q[0], f"goal back to the ship: {len(q)} steps to the warp to map 0x{nxt:02X} (Vermilion route)"
        step = _rom_step(pos, tile, grid_get)
        if step:
            return step, f"goal back to the ship: ROM route to the warp at ({x},{y}) toward Vermilion, steps unknown"
    return None


def _rom_step(pos: tuple, tile: tuple, grid_get=None) -> str | None:
    """First button of the ROM-grid par route to ``tile`` on this map (None without a ROM grid or a route)."""
    from pokeagent.legs import grid as G
    from pokeagent.legs.par import par
    global _grids
    try:
        if grid_get is None and _grids is False:
            _grids = G.rom_grids()  # loads the ROM once
        grid = grid_get(pos[0]) if grid_get else _grids(pos[0])
    except Exception:
        return None
    if grid is None:
        return None
    res = par(grid, (pos[1], pos[2]), (tile[1], tile[2]))
    if res is None or len(res[1]) < 2:
        return None
    a, b = res[1][0], res[1][1]
    return {(0, -1): "UP", (0, 1): "DOWN", (-1, 0): "LEFT", (1, 0): "RIGHT"}.get((b[0] - a[0], b[1] - a[1]))


def ship_gate_step(g: WorldGraph, goals: dict, stage: str | None, pos: tuple, grid_get=None) -> tuple[str, str] | None:
    if stage not in SHIP_STAGES:
        return None
    left_ship(goals, pos)
    return walk_off_step(goals, pos, g.maps) or route_back_step(g, goals, pos, grid_get) or ready_gate(g, goals, pos)
