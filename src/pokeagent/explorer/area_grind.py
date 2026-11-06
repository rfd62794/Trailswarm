"""area_grind: bound the Route 2 / Viridian Forest grind and the heal trips it provokes.

2026-11-06 seed 11: after to_route2 the agent roamed Route 2's grass below Brock's target, dropped under the 90% top-off
threshold, walked back to the Viridian Pokecenter, healed, came back, and repeated for 1,900 steps (8+ loops of ~190 steps).
The per-goal GrindBudget (2,500 steps / 25 battles) never fired inside a run. Two bounds, both per run:
  * the in-place grind on the grind maps ends after AREA_GRIND_STEPS planning steps or AREA_GRIND_BATTLES battles there;
  * the 90% top-off heal trip is only allowed MAX_TOPOFF_TRIPS times, then the plain 50% threshold applies.
"""
from __future__ import annotations

from pokeagent.explorer.planner import GRIND_IN_PLACE, MAX_TOPOFF_TRIPS
from pokeagent.explorer.world import POKECENTER_MAPS

AREA_GRIND_STEPS = 400
AREA_GRIND_BATTLES = 6


def note_map(ctx, m: int) -> None:
    """Count one heal trip each time the agent enters a Pokecenter from outside."""
    if m in POKECENTER_MAPS and ctx.last_plan_map not in POKECENTER_MAPS and ctx.last_plan_map != -1:
        ctx.heal_trips += 1
    ctx.last_plan_map = m


def capped_need(ctx, m: int, need: int, level: int, to_route2: bool) -> int:
    """``need``, or 0 (target lifted, head for Pewter) once the grind on the grind maps has used up its steps or battles."""
    g = ctx.area_grind
    if g.get("lifted"):
        return 0
    if not (to_route2 and m in GRIND_IN_PLACE and 0 < level < need):
        return need
    if g.get("battles0") is None:
        g["battles0"] = ctx.battles
    g["steps"] = g.get("steps", 0) + 1
    if g["steps"] >= AREA_GRIND_STEPS or ctx.battles - g["battles0"] >= AREA_GRIND_BATTLES:
        g["lifted"] = True
        ctx.log(f"[grind: {g['steps']} steps / {ctx.battles - g['battles0']} battles at L{level} (target L{need}): advancing toward Pewter]", "res")
        return 0
    return need
