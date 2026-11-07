"""Repel: use on a travel leg (a par-follow 'goal' trip) when the party is at readiness. Shield: never while grinding (``training``), never
under-level, never with a Magikarp trainee in the party (it levels on wild fights), never while one is already working, never in a fight.
ESCAPE ROPE stays with cave_escape."""
from __future__ import annotations

from pokeagent.explorer.item_policies import ids

REPEL_ACTIVE = 0xD0DB   # wRepelRemainingSteps


def should_use(*, bag: dict[int, int], trip: str | None, ready: bool, training: bool, active_steps: int, has_trainee: bool,
               battle: bool) -> tuple[int, None, str] | None:
    if trip != "goal" or not ready or training or active_steps > 0 or has_trainee or battle:
        return None
    for item in ids.REPELS:   # the cheapest first
        if bag.get(item, 0) > 0:
            return item, None, f"travel leg at readiness: {ids.name_of(item)} to skip wild fights"
    return None
