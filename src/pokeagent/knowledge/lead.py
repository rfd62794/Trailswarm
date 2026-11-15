"""Lead-ordering helpers: who stands at the front of the party.

team_plan.ascending_order is still THE ordering rule (lowest level first, fainted last); these sit on
top of it so that, when move data is loaded, a member that cannot hurt anything never leads - Gen 1
sends slot 0 into every battle and splits XP among the members that took part, so the weakest
DAMAGING member should lead, not a Harden-only cocoon (2026-11-14: a wild KAKUNA led every fight and
was ground to death pressing HARDEN).

Pure functions, same as the rest of team_plan: Combatants in, kb tables as arguments. No emulator.
"""
from __future__ import annotations

from pokeagent.knowledge.kb import table
from pokeagent.knowledge.team_plan import ascending_order


def can_damage(c, kb=None) -> bool:
    """True when any move of Combatant ``c`` has power above 0 in the moves table - a Harden-only KAKUNA is
    False (it can never hurt the foe). A move name missing from the table counts as power 0."""
    powers = {r.get("name"): (r.get("power") or 0) for r in table(kb, "moves").values()}
    return any(powers.get(m, 0) > 0 for m in getattr(c, "moves", ()) or ())


def lead_order(levels, fainted, can_dmg=None) -> list[int]:
    """The lead-picking order: like ascending_order, but a member that cannot hurt a foe sits behind every
    member that can - sort key (fainted, not can_dmg, level), so the weakest DAMAGING member leads and a
    Harden-only cocoon trails last. ``can_dmg=None`` (no move data) is exactly ascending_order."""
    if can_dmg is None:
        return ascending_order(levels, fainted)
    return sorted(range(len(levels)), key=lambda i: (bool(fainted[i]), not can_dmg[i], levels[i]))
