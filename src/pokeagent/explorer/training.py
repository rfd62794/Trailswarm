"""Training levels per campaign stage: a party readiness check, with one named table as the fallback.

Robert (2026-11-05): "We may have to look at variable Level Requirements based on Current Party." So the level wanted
before a stage is the lowest lead level at which OUR party (real stats, known moves, the type chart) beats the next boss's
party with margin (pokeagent.knowledge.readiness); a super-effective starter is ready earlier than a resisted one.
TRAIN_LEVEL_BY_GOAL is the fallback when the ROM tables or the party are missing; --train-level stays a hard floor.
"""
from __future__ import annotations

from pokeagent.goals import GOALS
from pokeagent.knowledge import trainers
from pokeagent.knowledge.readiness import Readiness, assess

# The lead's level wanted BEFORE the goal on the left is attempted; it applies from the previous entry's goal until this one lands.
# (Robert, 2026-11-05: two blackouts in Mt Moon at level 8; Misty's Staryu/Starmie are L18/L21.)
TRAIN_LEVEL_BY_GOAL = {"beat_brock": 12, "to_mt_moon": 14, "beat_misty": 20}
BOSS_LABEL = {"beat_brock": "BROCK", "to_mt_moon": "MT MOON", "beat_misty": "MISTY"}
_cache: dict = {}


def stage_goal(goals: dict) -> str | None:
    """The table goal the next unmet campaign goal leads up to (None once past the last)."""
    unmet = next((i for i, g in enumerate(GOALS) if not goals.get(g)), len(GOALS))
    return next((g for g in sorted(TRAIN_LEVEL_BY_GOAL, key=GOALS.index) if GOALS.index(g) >= unmet), None)


def readiness_for(goals: dict, party: list | None) -> Readiness | None:
    """Our party vs the stage boss (a gym leader; for Mt Moon the strongest trainer party on its floors); None without data."""
    goal = stage_goal(goals)
    if goal is None or not party:
        return None
    key = (goal, tuple(party))
    if key not in _cache:
        boss = trainers.boss_party(goal) or (trainers.strongest_on_mt_moon() if goal == "to_mt_moon" else [])
        _cache.clear() if len(_cache) > 64 else None
        _cache[key] = assess(party, boss, BOSS_LABEL[goal]) if boss else None
    return _cache[key]


def train_level_for(goals: dict, floor: int = 8, party: list | None = None) -> int:
    """Level wanted for the next unmet goal's stage: the readiness verdict for `party` when it can be computed,
    else the table; the --train-level flag (`floor`) is a hard floor under either."""
    goal = stage_goal(goals)
    if goal is None:
        return floor
    verdict = readiness_for(goals, party)
    return max(verdict.required if verdict else TRAIN_LEVEL_BY_GOAL[goal], floor)
