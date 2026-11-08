"""Next combat target on the route, and the engage / avoid / save / ignore decision per trainer.

Every threshold is a NAMED, untuned first value. The ROM trainer rows carry no facing and no sight
range, so SIGHT_GUESS guesses the line of sight (4 tiles in the four directions) and TRAINER_APPROACH
guesses where to stand to fight - both are flagged UNVERIFIED in every log line that leans on them.

The ``save`` action is REPORT-ONLY today: nothing acts on it (the grind report lists it; picking a saved
trainer for grinding is the follow-up Trainer_Grind_Pick_Directive).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer.perceive import DIRS
from pokeagent.explorer.trainer_ledger import TrainerEntry, TrainerLedger
from pokeagent.explorer.world import WorldGraph
from pokeagent.knowledge import readiness
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import trainer_mon

SIGHT_GUESS = 4                   # UNVERIFIED trainer line of sight, tiles, 4 directions (kb has no facing/range)
ENGAGE_MARGIN = readiness.MARGIN  # fight() score the party must clear to engage (0.30)
AVOID_BLOCK_FRAMES = 480          # routing-only block of sight-line tiles (same mechanism as temp_blocked); untuned
MAX_TARGET_DETOUR = 40            # path steps a target may add to the segment route; untuned
TRAINER_APPROACH = 2              # tiles before the trainer on the player's side to fight from; a guess
FAR = 1_000_000                   # the learned graph cannot reach the tile: farthest, not impossible


@dataclass(frozen=True)
class TrainerOption:
    entry: TrainerEntry
    steps: int
    margin: float | None
    action: str   # "engage" | "avoid" | "save" | "ignore"
    why: str


def sight_tiles(entry: TrainerEntry) -> list[tuple[int, int]]:
    """The guessed line of sight: SIGHT_GUESS tiles in each of the four directions from the placement
    (UNVERIFIED - the drained rows have no facing and no range)."""
    return [(entry.x + dx * k, entry.y + dy * k)
            for dx, dy in DIRS.values() for k in range(1, SIGHT_GUESS + 1)]


def approach_tile(entry: TrainerEntry, player: tuple[int, int, int]) -> tuple[int, int]:
    """TRAINER_APPROACH tiles in front of the placement toward the player (dominant axis; a guess)."""
    dx, dy = player[1] - entry.x, player[2] - entry.y
    if abs(dx) >= abs(dy):
        ux, uy = (dx > 0) - (dx < 0), 0
    else:
        ux, uy = 0, (dy > 0) - (dy < 0)
    return (entry.x + ux * TRAINER_APPROACH, entry.y + uy * TRAINER_APPROACH)


def fight_margin(party_now, mons, kb) -> float | None:
    """readiness.fight of the party (already carrying its CURRENT hp) against the ROM party."""
    theirs = [m for lv, n in mons if (m := trainer_mon(n, lv, kb))]
    moves = table(kb, "moves")
    if not party_now or not theirs or len(theirs) != len(mons) or not moves:
        return None
    chart = {(a, d): e for a, d, e in table(kb, "type_chart")}
    return readiness.fight(list(party_now), theirs, chart, moves)


def options(ledger: TrainerLedger, map_id: int, player: tuple[int, int, int], graph: WorldGraph,
            route_steps: int, party_now, kb=None, cat=None) -> list[TrainerOption]:
    """One option per ROM placement on the map, in ROM order.

    A beaten trainer is ``ignore``: never a target, never a frontier side, still impassable for routing
    (it is a person). ``unknown`` counts as unbeaten for targeting but is never a hazard - talking to a
    beaten trainer costs a few presses and resolves as talk_no_battle."""
    out = []
    for e in ledger.entries(map_id):
        if e.state == "beaten":
            out.append(TrainerOption(e, 0, None, "ignore", "beaten: not a target, still impassable"))
            continue
        appr = approach_tile(e, player)
        p = graph.path(player, lambda n, g=(map_id, appr[0], appr[1]): n == g)
        steps = len(p) if p is not None else FAR
        # the detour the fight adds to the segment route: an approach no farther than the goal is on the way
        on_route = steps <= route_steps
        detour = max(0, steps - route_steps)
        margin = fight_margin(party_now, e.mons, kb)
        if margin is None:
            out.append(TrainerOption(e, steps, None, "ignore", "no readiness data to sim the fight"))
        elif margin < ENGAGE_MARGIN:
            out.append(TrainerOption(e, steps, margin, "avoid",
                                     f"thin (margin {margin:+.2f}): bypass pending (SIGHT_GUESS={SIGHT_GUESS} unverified)"))
        elif on_route or detour <= MAX_TARGET_DETOUR:
            why = "on the route" if on_route else f"detour {detour} <= {MAX_TARGET_DETOUR}"
            out.append(TrainerOption(e, steps, margin, "engage", f"wins (margin {margin:+.2f}), {why}"))
        else:
            out.append(TrainerOption(e, steps, margin, "save",
                                     f"wins (margin {margin:+.2f}) but {detour} steps out: saved for grinding"))
    return out


def next_target(opts: list[TrainerOption]) -> TrainerOption | None:
    """The nearest ``engage`` along the route (smallest steps); ROM order breaks ties."""
    return min((o for o in opts if o.action == "engage" and o.steps < FAR),
               key=lambda o: (o.steps, o.entry.idx), default=None)


def block_sight(ctx, opt: TrainerOption, goal_fn, quiet: bool = False) -> str:
    """Routing-only avoidance: temp-block the sight line for AVOID_BLOCK_FRAMES, but ONLY while a route to
    the goal still exists with those tiles blocked. When the sight line IS the only route nothing is
    blocked and the decision downgrades to ``engage-forced`` (Nugget Bridge is a single lane)."""
    tiles = {(opt.entry.map, x, y) for x, y in sight_tiles(opt.entry)}
    now = {t for t, until in ctx.mem.temp_blocked.items() if until > ctx.frame}
    g = WorldGraph(ctx.mem.data["maps"])
    g.blocked_now = frozenset(now | tiles)
    e = opt.entry
    if g.path((ctx.view.m, ctx.view.x, ctx.view.y), goal_fn) is None:
        if not quiet:
            ctx.log(f"[trainer_route: {e.cls} p{e.party} sight line is the only route: engage-forced]", "res")
        return "engage-forced"
    for t in tiles:
        ctx.mem.temp_blocked[t] = ctx.frame + AVOID_BLOCK_FRAMES
    if not quiet:
        ctx.log(f"[trainer_route: avoiding {e.cls} p{e.party}: SIGHT_GUESS={SIGHT_GUESS} (unverified) line "
                f"blocked {AVOID_BLOCK_FRAMES} frames]", "res")
    return "avoid"
