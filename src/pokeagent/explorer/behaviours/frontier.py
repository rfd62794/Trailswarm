"""frontier: explore. New-map bursts, then the default rule: least-visited neighbour or a committed frontier route."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import lead_level, party_hp
from pokeagent.novelty import steer as novelty_steer

REVERSE_PENALTY = 2   # visits added to a direction that undoes the last successful move (choose_local)
TABU_LEN = 8          # tiles stood on in the last N moves on a map count +1 visit in choose_local
RETARGET_MARGIN = 3   # a new frontier must be this many steps closer to replace the committed target


def _tabu(ctx: ExplorerContext, map_id: int) -> set:
    return set(ctx.recent_tiles.get(map_id, ()))


def _frontier_move(ctx: ExplorerContext, m: int, x: int, y: int) -> tuple[str, str] | None:
    """Follow the committed frontier route press by press; re-plan only when the target is reached, the
    next step is blocked, the map changes, or the target stops being a frontier. A re-plan keeps the
    current target unless a new frontier is RETARGET_MARGIN steps closer (hysteresis)."""
    pos = (m, x, y)
    mem = ctx.mem
    if ctx.frontier_target is not None and ctx.frontier_target[0] != m:
        ctx.frontier_target = None  # a target on another map is meaningless here (and is_frontier would misjudge it)
        ctx.frontier_route = []
    if ctx.frontier_target == pos:
        ctx.frontier_target = None
        ctx.frontier_route = []
    if ctx.frontier_route and ctx.frontier_at is not None:
        emitted = ctx.frontier_route[0]
        if pos[0] != ctx.frontier_at[0]:
            ctx.frontier_route = []  # a map change invalidates the route
        elif pos != ctx.frontier_at:
            if ctx.last_press == emitted:
                ctx.frontier_route.pop(0)  # our step moved us: consume it
            else:
                ctx.frontier_route = []  # someone else moved us: the route no longer applies
        elif ctx.last_press == emitted:
            ctx.frontier_route = []  # our step was blocked: re-plan
        # else: another behaviour's press left us in place - the route still applies
    if ctx.frontier_target is not None and not mem.is_frontier(ctx.frontier_target):
        ctx.frontier_target = None
        ctx.frontier_route = []
    if ctx.frontier_route:
        ctx.frontier_at = pos
        t = ctx.frontier_target
        return ctx.frontier_route[0], f"frontier: {len(ctx.frontier_route)} steps left to ({t[1]},{t[2]})"
    ctx.frontier_at = None
    plan = mem.frontier_plan(m, x, y)
    if novelty_steer.active(ctx):  # explorer role only: prefer the frontier whose unexplored side the swarm has seen least
        plan = novelty_steer.plan(ctx, m, x, y) or plan
    if plan is None or not plan[1]:
        ctx.frontier_target = None
        return None
    node, route = plan
    cur = ctx.frontier_target
    if cur is not None:
        back = mem.route_to(m, x, y, cur)
        if back is not None and back[1] and len(back[1]) - len(route) < RETARGET_MARGIN:
            node, route = back  # keep the committed target unless the new one is >= RETARGET_MARGIN closer
    if not route:
        ctx.frontier_target = None
        return None
    ctx.frontier_target, ctx.frontier_route = node, list(route)
    ctx.frontier_at = pos
    return ctx.frontier_route[0], f"frontier: {len(ctx.frontier_route)} steps to ({node[1]},{node[2]})"


def _memory_step(ctx: ExplorerContext, m: int, x: int, y: int, *, avoid_maps=None, grass: str = "neutral"):
    """The shared explore pick: greedy neighbour choice, or the committed frontier route when every
    neighbour was already seen."""
    name, why, want_frontier = ctx.mem.choose_local(
        m, x, y, ctx.facing, ctx.view.tm, ctx.emu.read(0xD367),
        avoid_maps=avoid_maps, grass=grass,
        last_dir=ctx.last_dir, tabu=_tabu(ctx, m), reverse_penalty=REVERSE_PENALTY)
    if not want_frontier:
        return name, why
    step = _frontier_move(ctx, m, x, y)
    return step if step else (name, why)


class ExploreBurst(BehaviourBase):
    """A map NEW TO MEMORY (or a new item) earns a burst of maximal exploration before plans resume."""

    name = "explore_burst"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # the new-map bookkeeping must see every step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
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
            name, why = _memory_step(ctx, m, x, y, grass="neutral")
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
        hp_now, mx_now = party_hp(ctx.emu)
        goals_now_all = ctx.goals()
        weak = mx_now and hp_now / mx_now < 0.4
        training = (ctx.hunt_grass and not weak) or (goals_now_all.get("won_battle") and goals_now_all.get("to_route1") and 0 < lead_level(ctx.emu) < (max(8, ctx.train_need) if goals_now_all.get("to_route2") else 8) and not weak)
        name, why = _memory_step(ctx, m, x, y,
                                 avoid_maps={0x00} if (training and m == 0x0C) else None,
                                 grass="seek" if training else "avoid" if weak else "neutral")
        return Decision(name, "frontier", why)
