"""Trainers as one-time grind options: XP + the one-time prize vs the steps to reach and fight them,
ranked beside the wild spots. The prize is paid ONCE and a beaten trainer is off the board - the ledger
removes it. Pure module: the grind planner is unchanged; this feeds the report only (making GrindDrill
pick a trainer is the follow-up Trainer_Grind_Pick_Directive).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer.trainer_ledger import TrainerEntry, TrainerLedger
from pokeagent.explorer.trainer_route import fight_margin
from pokeagent.grind import atlas
from pokeagent.grind.xpmath import xp_gain
from pokeagent.knowledge import items_catalog, readiness

YEN_PER_XP = 0.5                 # untuned first value: 1 yen is worth half an XP point (finite money pool)
ENGAGE_MARGIN = readiness.MARGIN  # a grind never walks into a loss or a coin flip


@dataclass(frozen=True)
class TrainerGrind:
    entry: TrainerEntry
    xp: float
    prize: int | None
    steps: float
    xp_per_step: float
    margin: float
    value: float          # xp + prize * YEN_PER_XP: the one-time total


def trainer_xp(mons, base_exp: dict) -> float:
    """XP for sweeping the ROM party ``[(level, species)]``: xp_gain(base_exp[sp], level, trainer=True)."""
    return sum(xp_gain(base_exp.get(sp, 0), lv, trainer=True) for lv, sp in mons)


def spot_xp_per_step(s) -> float:
    """XP per step of a wild spot: a ``grind.atlas.Spot`` or its ``to_dict()`` row (the atlas shape). A row
    without ``xp_per_step`` (only ``xp_per_min``) is converted with atlas.STEPS_PER_MIN (225)."""
    if isinstance(s, dict):
        v = s.get("xp_per_step")
        return float(v) if v is not None else float(s.get("xp_per_min") or 0.0) / atlas.STEPS_PER_MIN
    return float(s.xp_per_step)


def spot_travel_steps(s) -> float:
    """The amortised Pokecenter trip of a wild spot (Spot attribute or atlas-row key); 0 when absent."""
    return float((s.get("travel_steps") if isinstance(s, dict) else getattr(s, "travel_steps", 0.0)) or 0.0)


def _travel(spots, x: int, y: int) -> float:
    """Steps to the trainer's tile: ``spots`` may be a callable (x, y) -> steps or the wild spots (Spot or
    atlas dict; the cheapest amortised Pokecenter trip stands in for travel)."""
    if callable(spots):
        return float(spots(x, y))
    return min((spot_travel_steps(s) for s in spots or ()), default=0.0)


def rank_trainer_grinds(ledger: TrainerLedger, map_id: int, party_now, base_exp: dict, cat, spots,
                      kb=None, top: int = 5) -> list[TrainerGrind]:
    """Unbeaten trainers the party beats with ENGAGE_MARGIN, best xp_per_step first. ``steps`` =
    PRIOR_BATTLE_STEPS + travel; beaten entries and fights the sim loses are dropped."""
    out = []
    for e in ledger.entries(map_id):
        if e.state == "beaten":
            continue
        margin = fight_margin(party_now, list(e.mons), kb)
        if margin is None or margin < ENGAGE_MARGIN:
            continue
        xp = trainer_xp(e.mons, base_exp)
        prize = items_catalog.trainer_prize(cat, e.cls, e.party) if cat else None
        steps = atlas.PRIOR_BATTLE_STEPS + _travel(spots, e.x, e.y)
        value = xp + (prize or 0) * YEN_PER_XP
        out.append(TrainerGrind(e, xp, prize, steps, value / steps if steps else 0.0, margin, value))
    return sorted(out, key=lambda g: -g.xp_per_step)[:top]
