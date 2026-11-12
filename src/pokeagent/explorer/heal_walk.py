"""heal_walk: walk to the nearest known Pokecenter and talk to the nurse, as a request that survives steps.

Why this exists (PR #159 review): ``ctx.center_intent`` means "I am inside a center on purpose", and PlanGoal
clears it the moment the player is on a non-center map, so setting it on the road requested nothing. The
planner's own heal path is tied to goal stages (planner*.py is not ours to edit), so the status-care / trainee
gate heal is a small walker of its own: the overworld leg is a BFS over the learned graph to any
POKECENTER_MAPS node (the same search outside_use.walk_to_center falls back to), the inside leg is the shape
every center shares (door (3,7), clear column x=3, counter row y=3, nurse answers from (3,3) facing UP).

The request lives in ``status_care.of(ctx)["walk"]`` and is carried out by the StatusCare behaviour, which
sits before PlanGoal in the registry, until the party is healed or the walk is abandoned with a logged reason
(no route, WALK_CAP steps, no progress). An abandoned walk cools down for COOLDOWN steps so a still-ineligible
trainee does not restart it every step.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.status_care import of, record_row, status_kinds
from pokeagent.explorer.world import POKECENTER_MAPS, WorldGraph
from pokeagent.ramstructs import read_party

WALK_CAP = 400       # steps one walk may take before it is abandoned (untuned first value)
COOLDOWN = 300       # steps an abandoned walk waits before a new request may start (untuned first value)
# The center layout (door (3,7), cross to x=3, nurse at (3,1), press A from (3,3) facing UP) is duplicated from
# planner.py:44-50 because planner.py is off-limits here; a later shared helper should replace both copies.
RETREAT_DONE = 0.95  # a precautionary walk (retreat_heal, after_victory) is over once the party is back at this HP fraction
COUNTER_X, COUNTER_Y = 3, 3   # the nurse (3,1) answers across the counter row, standing at (3,3) facing UP


def active(ctx) -> bool:
    return of(ctx).get("walk") is not None


def start(ctx, why: str, min_frac: float | None = None) -> bool:
    """Request a heal walk. False (nothing started) while one is running or cooling down after an abandon.
    ``min_frac``: a precautionary retreat (nobody fainted or poisoned yet) ends only once the whole party's HP is at or above
    this fraction, i.e. after the nurse; without it a hurt-but-standing party would read as "healed" on the next step."""
    st = of(ctx)
    if st.get("walk") is not None or ctx.step < st.get("walk_cool", 0):
        return False
    st["walk"] = {"why": why, "steps": 0, "from": ctx.step, "min_frac": min_frac}
    ctx.log(f"[heal_walk: start ({why})]", "res")
    record_row(ctx, {"event": "heal_walk_start", "why": why})
    return True


def _party_healed(ctx, min_frac: float | None = None) -> bool:
    """Nobody fainted and nobody poisoned (and, for a retreat walk, total HP at ``min_frac``): what a nurse visit leaves."""
    party = read_party(ctx.emu)
    if not (party and all(p.hp > 0 and "poison" not in status_kinds(p.status) for p in party)):
        return False
    return min_frac is None or sum(p.hp for p in party) >= min_frac * (sum(p.max_hp for p in party) or 1)


def _end(ctx, outcome: str, why: str, abandoned: bool) -> None:
    st = of(ctx)
    w = st.pop("walk", None) or {}
    if abandoned:
        st["walk_cool"] = ctx.step + COOLDOWN
    else:
        st["healed_at"] = ctx.step   # retreat_heal's cooldown: no new precautionary retreat right after a heal
    if ctx.center_intent == "status_care":
        ctx.center_intent = None
    ctx.log(f"[heal_walk: {outcome} after {w.get('steps', 0)} steps ({why})]", "res")
    record_row(ctx, {"event": f"heal_walk_{outcome}", "why": why, "steps": w.get("steps", 0)})


def step(ctx) -> Decision | None:
    """The next press of the active walk, or None (finished / abandoned / waiting on a text box)."""
    st = of(ctx)
    w = st.get("walk")
    if w is None:
        return None
    if _party_healed(ctx, w.get("min_frac")):
        _end(ctx, "healed", w["why"], False)
        return None
    w["steps"] += 1
    if w["steps"] > WALK_CAP:
        _end(ctx, "abandoned", f"{WALK_CAP} steps without being healed", True)
        return None
    m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
    if m in POKECENTER_MAPS:
        ctx.center_intent = "status_care"   # inside on purpose: the planner must not walk us back out
        if x != COUNTER_X:
            return Decision("RIGHT" if x < COUNTER_X else "LEFT", "heal_walk", "heal: crossing the Pokecenter to the counter")
        if y > COUNTER_Y:
            return Decision("UP", "heal_walk", "heal: walking up to the nurse")
        facing = ctx.facing == "UP"
        return Decision("A" if facing else "UP", "heal_walk", f"heal: at the nurse, {'talking' if facing else 'facing her'}")
    g = WorldGraph(ctx.mem.data.get("maps", {}))
    g.blocked_now = frozenset(ctx.mem.temp_blocked)
    found = g._bfs_node((m, x, y), lambda n: n[0] in POKECENTER_MAPS, 5000)   # not .path(): that sets par_follow's route
    if not found or not found[1]:
        _end(ctx, "abandoned", "no known route to a Pokecenter", True)
        return None
    return Decision(found[1][0], "heal_walk", f"heal: {len(found[1])} steps to a Pokecenter ({w['why']})")
