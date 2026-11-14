"""frontier: explore. New-map bursts, then the default rule: least-visited neighbour or a committed frontier route."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer import grind_episode, train_route
from pokeagent.explorer.training_ctl import exit_rule, sustain
from pokeagent.explorer.perceive import lead_level, party_needs_heal
from pokeagent.novelty import steer as novelty_steer

REVERSE_PENALTY = 2   # visits added to a direction that undoes the last successful move (choose_local)
TABU_LEN = 8          # tiles stood on in the last N moves on a map count +1 visit in choose_local
PATROL_REVERSE_PENALTY = 10_000  # no frontier left: walk on, turn round only when no other way is open (no dithering)
RETARGET_MARGIN = 3   # a new frontier must be this many steps closer to replace the committed target


def _tabu(ctx: ExplorerContext, map_id: int) -> set:
    return set(ctx.recent_tiles.get(map_id, ()))


def _frontier_move(ctx: ExplorerContext, m: int, x: int, y: int, allowed=None) -> tuple[str, str] | None:
    """Follow the committed frontier route press by press; re-plan only when the target is reached, the
    next step is blocked, the map changes, or the target stops being a frontier. A re-plan keeps the
    current target unless a new frontier is RETARGET_MARGIN steps closer (hysteresis). ``allowed`` is the
    grind episode's map set while one is active: no route may leave it (the Nugget Bridge ping-pong)."""
    pos = (m, x, y)
    mem = ctx.mem
    if allowed is not None and ctx.frontier_target is not None and ctx.frontier_target[0] not in allowed:
        ctx.frontier_target = None
        ctx.frontier_route = []
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
        if allowed is not None and grind_episode.leaves_set(ctx, ctx.frontier_route[0], allowed):
            ctx.frontier_target, ctx.frontier_route = None, []  # the route steps off the episode's maps: drop it
        else:
            ctx.frontier_at = pos
            t = ctx.frontier_target
            return ctx.frontier_route[0], f"frontier: {len(ctx.frontier_route)} steps left to ({t[1]},{t[2]})"
    ctx.frontier_at = None
    plan = mem.frontier_plan(m, x, y, allowed=allowed)
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


def _memory_step(ctx: ExplorerContext, m: int, x: int, y: int, *, avoid_maps=None, allowed=None, grass: str = "neutral"):
    """The shared explore pick: greedy neighbour choice, or the committed frontier route when every
    neighbour was already seen. With no frontier reachable the greedy pick would balance visit counts and
    dither between two tiles (Cerulean Gym corridor, 2026-11-07: 50-75% reversals), so it patrols instead."""
    def pick(reverse_penalty: int):
        return ctx.mem.choose_local(
            m, x, y, ctx.facing, ctx.view.tm, ctx.emu.read(0xD367),
            avoid_maps=avoid_maps, grass=grass,
            last_dir=ctx.last_dir, tabu=_tabu(ctx, m), reverse_penalty=reverse_penalty)
    first = pick(REVERSE_PENALTY)
    if first is None:
        return None  # boxed in by a memorised sign: no explore press (the caller yields or presses B)
    name, why, want_frontier = first
    if not want_frontier:
        return name, why
    step = _frontier_move(ctx, m, x, y, allowed)
    if step:
        return step
    patrol = pick(PATROL_REVERSE_PENALTY)
    if patrol is None:
        return None
    p_name, p_why, _ = patrol
    if allowed is not None and grind_episode.leaves_set(ctx, p_name, allowed):
        # a patrol step must not leave the episode's map set either: the plain pick if it stays, else A in place
        return (name, why) if not grind_episode.leaves_set(ctx, name, allowed) else ("A", "episode boundary: patrol stays on the map set")
    return p_name, f"{p_why} (no frontier: patrolling)"


class ExploreBurst(BehaviourBase):
    """A map NEW TO MEMORY (or a new item) earns a burst of maximal exploration before plans resume."""

    name = "explore_burst"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # the new-map bookkeeping must see every step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        ctx.goals()
        if ctx.known_maps_at_start is None:
            ctx.known_maps_at_start = {int(k) for k in ctx.mem.data["maps"] if len(ctx.mem.data["maps"][k].get("visited", {})) >= 5}
        if m not in ctx.burst_maps:  # a map NEW TO MEMORY: maximal exploration before plans resume
            ctx.burst_maps.add(m)
            if m not in ctx.known_maps_at_start:
                ctx.explore_burst = max(ctx.explore_burst, 120)
                ctx.log(f"[new map 0x{m:02X}: exploration burst, 120 steps before plans resume]", "res")
        if ctx.explore_burst > 0 and not party_needs_heal(ctx.emu, 0.4):
            ctx.explore_burst -= 1
            picked = _memory_step(ctx, m, x, y, grass="neutral")
            if picked is None:
                return None  # boxed in by a memorised sign: let the planner move us instead of looping A->B
            name, why = picked
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
        goals_now_all = ctx.goals()
        weak = sustain.heal_now(ctx).weak  # while grinding: the survival floor, not a fixed 40%
        floor_hold = exit_rule.floor_hold(ctx)  # boss held shut by the team floor: find grass, never the leader
        training = ((ctx.hunt_grass or floor_hold) and not weak) or (goals_now_all.get("won_battle") and goals_now_all.get("to_route1") and 0 < lead_level(ctx.emu) < (max(8, ctx.train_need) if goals_now_all.get("to_route2") else 8) and not weak)
        ep = grind_episode.active(ctx)
        allowed = frozenset(ep["maps"] | {m}) if ep else None
        picked = _memory_step(ctx, m, x, y,
                                 avoid_maps=train_route.stay_on_route(m, ctx.train_route_live, ep, ctx.mem.data["maps"]) or
                                 ({0x00} if (training and m == 0x0C) else None),
                                 allowed=allowed,
                                 grass="seek" if training else "avoid" if weak else "neutral")
        if picked is None:
            return Decision("B", "frontier", "every direction known blocked; the tile in front is a memorised sign: B")
        name, why = picked
        return Decision(name, "frontier", why)
