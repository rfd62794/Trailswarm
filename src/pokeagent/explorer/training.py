"""Training levels per campaign stage: one named table instead of a single --train-level default."""
from __future__ import annotations

from pokeagent.goals import GOALS

# The lead's level wanted BEFORE the goal on the left is attempted; it applies from the previous entry's goal until this one lands.
# (Robert, 2026-11-05: two blackouts in Mt Moon at level 8; Misty's Staryu/Starmie are L18/L21.)
TRAIN_LEVEL_BY_GOAL = {"beat_brock": 12, "to_mt_moon": 14, "beat_misty": 20}


def train_level_for(goals: dict, floor: int = 8) -> int:
    """Level wanted for the next unmet goal's stage; the --train-level flag is a floor under the table."""
    unmet = next((i for i, g in enumerate(GOALS) if not goals.get(g)), len(GOALS))
    for goal in sorted(TRAIN_LEVEL_BY_GOAL, key=GOALS.index):
        if GOALS.index(goal) >= unmet:
            return max(TRAIN_LEVEL_BY_GOAL[goal], floor)
    return floor
