"""Grind budget: the training gate (planner: 'level < _train_level -> go grind') must not hold the run forever.

Lift the gate for a goal when grinding stops paying: N training battles or M training steps without a level gain on the lead,
the lead at or above the training route's top wild level + 6 (XP per fight is negligible), or blackouts in a row while training.
"""
from __future__ import annotations

GRIND_BATTLES = 25
GRIND_STEPS = 2500
GRIND_BLACKOUTS = 2
CEILING_MARGIN = 6   # lead this far above the route's top wild level: a fight there gives negligible XP


def battle_outcome(*, trainer: bool, start: tuple, end: tuple, party_count: int) -> tuple[bool, bool]:
    """(won, moved_away) from where the battle began and where it ended.
    A trainer battle cannot be fled, and a loss warps you to another MAP (a Pokecenter): so a trainer fight is won when we
    are still on the battle's map, even if the trainer walked us a tile or a door away (2026-11-06: five S.S. Anne wins were
    recorded as lost 'with HP left', and counted as blackouts). A wild fight keeps the exact-tile test: staying put is a win
    or a flee (not told apart here), moving off the tile is a blackout."""
    if trainer:
        gone = end[0] != start[0]
        return party_count > 0 and not gone, party_count > 0 and gone
    return party_count > 0 and end == start, party_count > 0 and end != start


def record_battle_result(ctx, *, won: bool, moved_away: bool) -> None:
    """Blackouts in a row: a lost battle that warped us away counts, a win resets, a flee (same spot) changes nothing."""
    if won:
        ctx.blackouts_row = 0
    elif moved_away:
        ctx.blackouts_row = ctx.blackouts_row + 1


class GrindBudget:
    """Per-goal counters of training effort since the lead last gained a level."""

    def __init__(self) -> None:
        self._s: dict[str, dict] = {}
        self._lifted: dict[str, str] = {}

    def lifted(self, goal: str) -> bool:
        return goal in self._lifted

    def reason(self, goal: str) -> str:
        return self._lifted.get(goal, "")

    def update(self, goal: str, *, level: int, step: int, battles: int, blackouts: int, training: bool,
               ceiling: int | None = None) -> str | None:
        """Feed one planning step; returns the reason the first time the gate for `goal` is lifted, else None."""
        if goal in self._lifted:
            return None
        s = self._s.setdefault(goal, {"level": level, "step": step, "battles": battles, "steps_in": 0, "battles_in": 0})
        if level > s["level"]:
            s.update(level=level, steps_in=0, battles_in=0)
        if training:
            s["steps_in"] += max(0, step - s["step"])
            s["battles_in"] += max(0, battles - s["battles"])
        s["step"], s["battles"] = step, battles
        if not training:
            return None
        why = None
        if s["battles_in"] >= GRIND_BATTLES:
            why = f"{GRIND_BATTLES} battles without a level gain (stuck at L{level})"
        elif s["steps_in"] >= GRIND_STEPS:
            why = f"{GRIND_STEPS} steps without a level gain (stuck at L{level})"
        elif ceiling is not None and level >= ceiling + CEILING_MARGIN:
            why = f"lead L{level} is {CEILING_MARGIN}+ levels above the route's wild ceiling L{ceiling}: no XP left to grind"
        elif blackouts >= GRIND_BLACKOUTS:
            why = f"{blackouts} blackouts in a row while training"
        if why:
            self._lifted[goal] = why
        return why
