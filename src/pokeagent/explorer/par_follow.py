"""par_follow: walk plan_goal's route along the cheapest ROM path instead of the learned-world BFS path.

plan_goal's planner picks a TARGET on the current map (the tile before the next warp or map edge, or a spot to stand on) but
walks to it over the learned graph, which is a breadth-first path through tiles seen so far: it zig-zags, and a phantom warp in
memory (a "door" the ROM header does not have) sends it back and forth for thousands of presses. Here the target is kept and the
route is recomputed on the ROM grid (legs.par: 16 frames a tile, grass penalty, ledge hops). One button is emitted per step;
the route is rebuilt from the current tile each step, so every replan condition falls out of the blocked set:
  * a failed press (same tile, our own press) blocks the tile ahead for BLOCK_STEPS steps; MAX_FAILS in a row hand the
    leg back to the planner for COOLDOWN steps;
  * sprite tiles (people) and ``ctx.mem.temp_blocked`` tiles are blocked for routing only, so we never press into a person;
  * a map change resets the state (the target is per map).
Anything this module cannot judge (no ROM grid, unreachable under the blocks, target is a person) returns the planner's press
unchanged. A learned warp whose tile the ROM header lacks is forgotten (recoverable) instead of walked to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pokeagent.explorer.perceive import lead_level
from pokeagent.explorer.world import POKECENTER_MAPS, WorldGraph
from pokeagent.legs import grid as G
from pokeagent.legs.par import par

BLOCK_STEPS = 40   # a failed press blocks the tile ahead this many steps
MAX_FAILS = 4      # failed presses in a row before the leg goes back to the planner
COOLDOWN = 60      # steps the planner drives after MAX_FAILS
_BUTTON = {v: k for k, v in G.DIRS.items()}
_grids: Any = False  # lazy rom_grids(): False = not tried, None = no ROM


@dataclass
class ParState:
    get: Any = None                                   # get(map_id) -> Grid | None (tests inject; default = the ROM)
    map: int | None = None
    blocked: dict = field(default_factory=dict)       # (map, x, y) -> step it expires
    last: tuple | None = None                         # (pos, button, step) of our latest press
    fails: int = 0
    cooldown_until: int = 0

    def grid(self, m: int):
        global _grids
        if self.get is not None:
            return self.get(m)
        if _grids is False:
            _grids = G.rom_grids()
        return _grids(m) if _grids else None


def exit_walk(maps: dict, start: tuple, buttons: list) -> tuple:
    """Follow ``buttons`` through the learned warps/ledges from ``start`` while on its map.
    Returns (target (x, y), leaving button | None, warp key | None): the last tile on the map and the press that leaves it."""
    m, x, y = start
    d = maps.get(str(m), {})
    for b in buttons:
        key = f"{x},{y},{b}"
        if key in d.get("warps", {}):
            return (x, y), b, key
        hop = d.get("jumps", {}).get(key)
        if hop:
            x, y = hop[0], hop[1]
        else:
            dx, dy = G.DIRS[b]
            x, y = x + dx, y + dy
    return (x, y), None, None


def legit_exit(g, tile: tuple, button: str) -> bool:
    """The press steps onto a ROM warp tile or off the map edge (a real way out)."""
    dx, dy = G.DIRS[button]
    nx, ny = tile[0] + dx, tile[1] + dy
    return tile in g.solid or (nx, ny) in g.solid or not g.inside(nx, ny)


def _settle(ctx, st: ParState, pos: tuple) -> None:
    """Judge our previous press: unchanged tile with nobody else pressing in between = it failed."""
    if st.map != pos[0]:
        st.map, st.blocked, st.last, st.fails = pos[0], {}, None, 0
    if st.last is None:
        return
    (lpos, btn, step), st.last = st.last, None
    if lpos != pos:
        st.fails = 0
    elif ctx.step == step + 1 and ctx.last_press == btn:
        dx, dy = G.DIRS[btn]
        st.blocked[(pos[0], pos[1] + dx, pos[2] + dy)] = ctx.step + BLOCK_STEPS
        st.fails += 1
        if st.fails >= MAX_FAILS:
            st.cooldown_until, st.fails = ctx.step + COOLDOWN, 0


def _routing_blocks(ctx, st: ParState, m: int, sprites: list) -> set:
    out = {(x, y) for pic, x, y in sprites}
    out |= {(t[1], t[2]) for t, exp in getattr(ctx.mem, "temp_blocked", {}).items() if t[0] == m and exp > ctx.frame}
    out |= {(t[1], t[2]) for t, exp in st.blocked.items() if t[0] == m and exp > ctx.step}
    return out


def _next_button(a: tuple, b: tuple) -> str:
    dx, dy = (b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1])
    return _BUTTON[(dx, dy)]


# Trips with a concrete destination. Exploration (frontier, explore_burst, the planner's "northernmost known tile" and
# "unexplored door" probes) is never par-driven: the campaign needs it to learn the map.
EXPLORING = ("northernmost", "unexplored")


def training(ctx) -> bool:
    """The agent is levelling: the lead is below the training target (frontier seeks grass, area_grind / GrindBudget fight on).
    plan_goal clears ``ctx.train_need`` to 0 once the grind budget is spent or the bandit skips the grind."""
    level = (getattr(ctx, "gate_lvl", None) or lead_level(ctx.emu))  # team_ready: the Magikarp trainee band
    return 0 < level < (ctx.train_need or 0)


def eligible_trip(ctx, why: str) -> str | None:
    """The kind of purposeful trip a planner press belongs to ("heal", "mart", "goal"), or None when par must not drive it."""
    if getattr(ctx, "shop_intent", None):   # hook: the ball-buying builder sets ctx.shop_intent while walking to a Mart
        return "mart"
    if why.startswith("HP ") and ("Pokecenter" in why or "Mom" in why):
        return "heal"   # home to Mom / to the nearest Pokecenter (planner heal rules)
    if ctx.center_intent and ctx.view.m in POKECENTER_MAPS:
        return "heal"
    if training(ctx):
        return None     # levelling is deliberately not par: grass seeking and grind fights stay with the Explorer
    if why.startswith("goal") and "steps" in why and not any(k in why for k in EXPLORING):
        return "goal"   # a known exit / warp / spot on the learned route
    return None


def refine(ctx, planned: tuple, sprites: list) -> tuple[tuple, str]:
    """``(planned, driver)``: planned = (button, why) from plan_step; sprites = [(pic, x, y)] of people on this map.
    driver is "par" when the press is par_follow's, else "" and planned is returned untouched."""
    route, WorldGraph.last_route = WorldGraph.last_route, None
    st = ctx.par or ParState()
    ctx.par = st
    m, x, y = pos = (ctx.view.m, ctx.view.x, ctx.view.y)
    _settle(ctx, st, pos)
    if eligible_trip(ctx, planned[1]) is None:
        return planned, ""
    if route is None or route[0] != pos or route[2][0] != planned[0] or ctx.step < st.cooldown_until:
        return planned, ""   # not a path press (talk, face, heal) or cooling down
    g = st.grid(m)
    if g is None:
        return planned, ""
    target, leave, key = exit_walk(ctx.mem.data["maps"], pos, route[2])
    if leave is not None and not legit_exit(g, target, leave):
        ctx.mem.forget_warp(m, key)  # the ROM has no door here: stop walking to it (recoverable; learn() needs two sightings)
        ctx.log(f"[par_follow: forgot phantom warp {m}:{key}, not a ROM warp or map edge]", "res")
        return planned, ""
    if target == (x, y) or target in {(sx, sy) for _p, sx, sy in sprites}:
        return planned, ""
    blocks = _routing_blocks(ctx, st, m, sprites) - {target, (x, y)}
    if blocks:
        walk = g.walk.copy()
        for bx, by in blocks:
            if g.inside(bx, by):
                walk[by, bx] = False
        g = G.Grid(walk, g.grass, g.solid, g.jumps, g.walls)
    res = par(g, (x, y), target)
    if res is None or len(res[1]) < 2:
        return planned, ""
    button = _next_button((x, y), res[1][1])
    st.last = (pos, button, ctx.step)
    return (button, f"par: {len(res[1]) - 1} steps to ({target[0]},{target[1]}) [{planned[1]}]"), "par"
