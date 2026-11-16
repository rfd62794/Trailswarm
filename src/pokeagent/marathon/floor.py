"""The team level floor a marathon grind stage trains toward, judged from levels.jsonl alone.

knowledge.team_floor.check cannot run here: its "sendable" test needs each member's moves against
the boss party, and levels.jsonl party rows carry only ``[species, level, exp, hp, max_hp]``. The
marathon floor is the same level sources - FLOOR_BY_GOAL first, TRAIN_LEVEL_BY_GOAL as the
fallback - over the party's non-Magikarp members, the same TEAM_FLOOR_MEMBERS count capped at the
members there are. Pure functions; reader.RunView calls them per levels row.
"""
from __future__ import annotations


def level_for(goal: str) -> int | None:
    """The floor level for ``goal``: FLOOR_BY_GOAL first, else the TRAIN_LEVEL_BY_GOAL fallback;
    None when neither names it - the reader keeps the old any-gain behaviour for such goals."""
    try:
        from pokeagent.explorer.training import TRAIN_LEVEL_BY_GOAL
        from pokeagent.knowledge.team_floor import FLOOR_BY_GOAL
    except Exception:  # knowledge tables unavailable: no floor to judge a gain against
        return None
    return FLOOR_BY_GOAL.get(goal, TRAIN_LEVEL_BY_GOAL.get(goal))


def _levels(party) -> list[int]:
    """Levels of the non-Magikarp members in a levels.jsonl party row (Magikarp can never fill the
    floor - team_floor.check's sendable test excludes it the same way)."""
    from pokeagent.ram_symbols import SPECIES_MAGIKARP
    out = []
    for m in party or ():
        try:
            sp, lv = int(m[0]), int(m[1])
        except (IndexError, TypeError, ValueError):
            continue
        if sp != SPECIES_MAGIKARP:
            out.append(lv)
    return out


def toward(cur_party, prev_party, level: int) -> bool:
    """Whether the gain between two consecutive levels.jsonl party rows moved the team toward the
    floor: another non-Magikarp member reached ``level``, or - the floor still unmet - the best
    under-floor member's level rose. False once the floor is met."""
    from pokeagent.knowledge.team_floor import TEAM_FLOOR_MEMBERS
    prev, cur = _levels(prev_party), _levels(cur_party)
    have_prev = sum(lv >= level for lv in prev)
    if have_prev >= min(TEAM_FLOOR_MEMBERS, len(prev)):
        return False
    if sum(lv >= level for lv in cur) > have_prev:
        return True
    under = [max((lv for lv in rows if lv < level), default=0) for rows in (prev, cur)]
    return under[1] > under[0]
