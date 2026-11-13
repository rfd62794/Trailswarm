"""Per-checkpoint team level floor (Robert, 2026-11-12: "the level requirements should account for the whole team, as a
combination, but also account for a minimum level for the team for each major checkpoint").

The gym verdict stays the whole-party fight sim (team_plan.boss_need: best opener plus switch-ins; no single slot gates a
gym). The floor is a SECOND condition on the same verdict: ready = sim passes AND the floor is met. Pure: no emulator.

Floor met = at least TEAM_FLOOR_MEMBERS sendable, non-Magikarp members at or above the checkpoint's floor level. The
alternative ("fighter above floor+3 and one more member at the floor") is nearly subsumed by this one (that fighter is
itself over the floor) and adds a second magic number, so the simple count wins. "Sendable" = has a damaging move that
hurts at least one boss mon: the sim would never send a member that cannot (a KAKUNA vs Starmie), so it neither counts
toward the floor nor becomes the training target. The count is capped at the sendable members there are, so a party with
one useful member is not held on a floor nothing can fix.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import trainer_mon
from pokeagent.knowledge.readiness import _chart, best_move

TEAM_FLOOR_MEMBERS = 2  # members that must be at the floor; untuned

# goal -> minimum team level. UNTUNED first values = the leader's ace level minus 2. Aces (top level of the ROM party,
# the same figures as training.TRAIN_LEVEL_BY_GOAL's fallback comment): Brock Onix 14, Misty Starmie 21, Surge Raichu 24,
# Erika Vileplume 29, Koga Weezing 43, Sabrina Alakazam 43, Blaine Arcanine 47, Giovanni Rhydon 50, Lorelei (the Elite
# Four entry goal, e4 door -> Lorelei's room) Lapras 56.
FLOOR_BY_GOAL = {"beat_brock": 12, "beat_misty": 19, "beat_surge": 22, "beat_erika": 27, "beat_koga": 41,
                 "beat_sabrina": 41, "beat_blaine": 45, "beat_giovanni": 48, "beat_lorelei": 54}


@dataclass(frozen=True)
class Floor:
    met: bool
    level: int
    need: int                 # members required (TEAM_FLOOR_MEMBERS, capped at the sendable members)
    have: int                 # sendable non-Magikarp members at or above `level`
    target_slot: int | None   # the sendable member closest below the floor; None when met or nobody can be trained
    text: str                 # "" when met, else the logged failing reason


def sendable_slots(party, boss, kb=None) -> list[int]:
    """Slots of non-Magikarp members with a damaging move that hurts at least one boss mon."""
    theirs = [m for lv, n in boss if (m := trainer_mon(n, lv, kb))]
    moves = table(kb, "moves")
    if not theirs or not moves:
        return []
    chart = _chart(kb)
    return [i for i, c in enumerate(party)
            if c.name != "MAGIKARP" and any(best_move(c, f, chart, moves)[0] > 0 for f in theirs)]


def check(goal: str, party, boss, kb=None) -> Floor | None:
    """The floor verdict for `goal`; None when the goal has no floor or the data is missing (the sim alone decides)."""
    level = FLOOR_BY_GOAL.get(goal)
    if level is None or not party or not boss:
        return None
    slots = sendable_slots(party, boss, kb)
    if not slots:
        return None
    need = min(TEAM_FLOOR_MEMBERS, len(slots))
    have = sum(party[i].level >= level for i in slots)
    if have >= need:
        return Floor(True, level, need, have, None, "")
    below = [i for i in slots if party[i].level < level]
    target = max(below, key=lambda i: (party[i].level, -i), default=None)   # closest below: the cheapest raise
    return Floor(False, level, need, have, target,
                 f"team floor for {goal}: need {need} members >= L{level}, have {have}")


def ready(nv, floor: Floor | None) -> bool:
    """The ONE gym verdict: the whole-party sim passes AND the floor is met (no floor data: the sim alone)."""
    return bool(nv is not None and nv.ready and (floor is None or floor.met))
