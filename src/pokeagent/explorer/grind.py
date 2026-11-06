"""Grind budget: the training gate (planner: 'level < _train_level -> go grind') must not hold the run forever.

Lift the gate for a goal when grinding stops paying: N training battles or M training steps without a level gain on the lead,
the training route's wild level ceiling below the required level minus 2, or blackouts in a row while training.
"""
from __future__ import annotations

GRIND_BATTLES = 25
GRIND_STEPS = 2500
GRIND_BLACKOUTS = 2
CEILING_SLACK = 2


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
               ceiling: int | None = None, required: int = 0) -> str | None:
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
        elif ceiling is not None and required and ceiling < required - CEILING_SLACK:
            why = f"route ceiling L{ceiling} is below the required L{required} minus {CEILING_SLACK}"
        elif blackouts >= GRIND_BLACKOUTS:
            why = f"{blackouts} blackouts in a row while training"
        if why:
            self._lifted[goal] = why
        return why
