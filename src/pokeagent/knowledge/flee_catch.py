"""flee_catch: wild species that can end the battle on their own turn - the ball must go first.

pokered: a wild Pokemon whose only move is Teleport (Abra, Rte 24/25) uses it on ITS turn and is
gone, so weakening it first forfeits the catch. ``flee_on_turn`` is the one predicate catch_policy
consults before its usual status/damage/weaken order: a named flee species, or any wild whose known
moves are ALL battle-enders. UNVERIFIED (controller note): wild Abra at L8-12 knows only Teleport -
the species table covers it whether or not the learnset does.
"""
from __future__ import annotations

FLEE_SPECIES = frozenset({"ABRA"})
FLEE_MOVES = frozenset({"TELEPORT", "ROAR", "WHIRLWIND"})   # moves that end a wild battle on the user's turn
ABRA_LINE = frozenset({"ABRA", "KADABRA", "ALAKAZAM"})       # the --build abra line: any member settles catch_abra


def flee_on_turn(name: str | None, moves) -> bool:
    """True when the wild mon can leave on its own turn: a named flee species, or one whose every
    known move is a battle-ender (no move data -> False: cannot judge)."""
    if name in FLEE_SPECIES:
        return True
    known = {m for m in moves or () if m}
    return bool(known) and known <= FLEE_MOVES
