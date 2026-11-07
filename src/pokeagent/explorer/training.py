"""Training levels per campaign stage: a party readiness check, with one named table as the fallback.

Robert (2026-11-05): "We may have to look at variable Level Requirements based on Current Party." So the level wanted
before a stage is the lowest lead level at which OUR party (real stats, known moves, the type chart) beats the next boss's
party with margin (pokeagent.knowledge.readiness); a super-effective starter is ready earlier than a resisted one.
TRAIN_LEVEL_BY_GOAL is the fallback when the ROM tables or the party are missing; --train-level stays a hard floor.
"""
from __future__ import annotations

from pokeagent.explorer.world import DUNGEON_MAPS
from pokeagent.goals import GOALS
from pokeagent.knowledge import trainers
from pokeagent.knowledge.readiness import Readiness, assess

# The lead's level wanted BEFORE the goal on the left is attempted; it applies from the previous entry's goal until this one lands.
# (Robert, 2026-11-05: two blackouts in Mt Moon at level 8; Misty's Staryu/Starmie are L18/L21.)
TRAIN_LEVEL_BY_GOAL = {"beat_brock": 12, "to_mt_moon": 14, "beat_misty": 20}
BOSS_LABEL = {"beat_brock": "BROCK", "to_mt_moon": "MT MOON", "beat_misty": "MISTY"}
CAP_ABOVE_TABLE = 5
_cache: dict = {}


MT_MOON_FLOOR_GOALS = frozenset({"mt_moon_b1f", "mt_moon_b2f", "through_mt_moon"})  # still the Mt Moon stage, not Misty's


def stage_goal(goals: dict) -> str | None:
    """The table goal the next unmet campaign goal leads up to (None once past the last). The cave floors belong to
    the Mt Moon stage: 2026-11-05 they read as Misty's (L24) because to_mt_moon had already landed on entering 1F."""
    unmet = next((i for i, g in enumerate(GOALS) if not goals.get(g)), len(GOALS))
    if unmet < len(GOALS) and GOALS[unmet] in MT_MOON_FLOOR_GOALS:
        return "to_mt_moon"
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


def before_route2(goals: dict) -> bool:
    """True until Route 2 has been reached: to_viridian, oaks_parcel and deliver_parcel only ask for the floor level."""
    return not goals.get("to_route2")


def required_level(goals: dict, floor: int = 8, party: list | None = None) -> tuple[int, str]:
    """(level wanted, clamp note). The readiness verdict is clamped to the table value + CAP_ABOVE_TABLE (a sane grind
    distance: a counter catch is the answer past it); the --train-level flag (`floor`) stays a hard floor above the clamp."""
    goal = stage_goal(goals)
    if goal is None:
        return floor, ""
    if before_route2(goals):  # the Brock target must not hold the run on Route 1 before Viridian (2026-11-06: 1,700 steps)
        return floor, ""
    verdict, table = readiness_for(goals, party), TRAIN_LEVEL_BY_GOAL[goal]
    if not verdict:
        return max(table, floor), ""
    cap = table + CAP_ABOVE_TABLE
    note = f"clamp L{verdict.required} -> L{cap} vs {BOSS_LABEL[goal]}: consider a counter catch" if verdict.required > cap else ""
    return max(min(verdict.required, cap), floor), note


def train_level_for(goals: dict, floor: int = 8, party: list | None = None) -> int:
    """Level wanted for the next unmet goal's stage (see required_level)."""
    return required_level(goals, floor, party)[0]


def gate_for(map_id: int, need: int) -> int:
    """The training level the planner may enforce on this map: none (0) inside a dungeon, ``need`` elsewhere."""
    return 0 if map_id in DUNGEON_MAPS else need
