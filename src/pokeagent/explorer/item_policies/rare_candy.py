"""RARE CANDY: held until it buys something. Shield: never on a Magikarp trainee (it levels by sharing XP, and a candy there is lost
on a mon that cannot fight a boss), never above L99. Use on the fighter when (a) the under-level gap is within the candies held and
a boss segment is next, or (b) the grind atlas says the remaining XP is more than GRIND_MINUTES_MAX of grinding away."""
from __future__ import annotations

from pokeagent.explorer.item_policies import ids
from pokeagent.explorer.item_policies.view import MAGIKARP, Mon, fighter_slot_of

GRIND_MINUTES_MAX = 15.0   # a grind longer than this is worth a candy (each one skips a level's XP)
MAX_LEVEL = 99
STEPS_PER_MIN = 225.0      # grind.atlas.STEPS_PER_MIN (3600 / 16); copied because explorer/ may not import pokeagent.grind (a test pins them equal)


def should_use(*, candies: int, party: list[Mon], gap: tuple[int, int, int] | None, boss_next: bool,
               grind_minutes: float | None) -> tuple[int, int, str] | None:
    """gap = training.under_level(...) = (needed, current, gap) or None when the fighter is already at the level wanted."""
    slot = fighter_slot_of(party)
    if candies <= 0 or gap is None or slot is None:
        return None
    mon = party[slot]
    if mon.species == MAGIKARP or mon.level >= MAX_LEVEL:
        return None
    needed, current, missing = gap
    if boss_next and missing <= candies:
        return ids.RARE_CANDY, slot, f"gap L{current} -> L{needed} is {missing} level(s), {candies} candy held, a boss is next"
    if grind_minutes is not None and grind_minutes > GRIND_MINUTES_MAX:
        return ids.RARE_CANDY, slot, f"grinding to L{needed} would take {grind_minutes:.0f} min (> {GRIND_MINUTES_MAX:.0f})"
    return None


def atlas_minutes(atlas: dict, starter: str, goal: str, level: int, steps_per_min: float) -> float | None:
    """Minutes to the goal's level at the best grind spot, from runs/grind_atlas.json's ``atlas`` section
    ({starter: {goal: {level bucket: [spot dicts]}}}); uses the nearest bucket at or below ``level``. None when unknown."""
    buckets = ((atlas.get(starter) or {}).get(goal)) or {}
    below = sorted((int(k) for k in buckets if int(k) <= level), reverse=True)
    spots = buckets.get(str(below[0])) if below else None
    steps = [s["steps_to_goal"] for s in spots or [] if s.get("steps_to_goal")]
    return min(steps) / steps_per_min if steps and steps_per_min > 0 else None
