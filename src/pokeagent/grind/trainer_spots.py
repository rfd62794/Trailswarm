"""Trainers as one-time grind options: XP + the one-time prize vs the steps to reach and fight them,
ranked beside the wild spots. The prize is paid ONCE and a beaten trainer is off the board - the ledger
removes it. Pure module: the grind planner is unchanged; this feeds the report only (making GrindDrill
pick a trainer is the follow-up Trainer_Grind_Pick_Directive).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer.trainer_ledger import TrainerEntry, TrainerLedger
from pokeagent.grind.atlas import PRIOR_BATTLE_STEPS
from pokeagent.grind.xpmath import xp_gain
from pokeagent.knowledge import items_catalog, readiness
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import trainer_mon

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


def _margin(party_now, mons, kb) -> float | None:
    theirs = [m for lv, n in mons if (m := trainer_mon(n, lv, kb))]
    moves = table(kb, "moves")
    if not party_now or not theirs or len(theirs) != len(mons) or not moves:
        return None
    chart = {(a, d): e for a, d, e in table(kb, "type_chart")}
    return readiness.fight(list(party_now), theirs, chart, moves)


def _travel(spots, x: int, y: int) -> float:
    """Steps to the trainer's tile: ``spots`` may be a callable (x, y) -> steps or the wild Spot list
    (its cheapest amortised Pokecenter trip stands in for travel)."""
    if callable(spots):
        return float(spots(x, y))
    try:
        return float(min((s.travel_steps for s in spots), default=0.0))
    except (TypeError, AttributeError):
        return 0.0


def rank_trainer_grinds(ledger: TrainerLedger, map_id: int, party_now, base_exp: dict, cat, spots,
                      kb=None, top: int = 5) -> list[TrainerGrind]:
    """Unbeaten trainers the party beats with ENGAGE_MARGIN, best xp_per_step first. ``steps`` =
    PRIOR_BATTLE_STEPS + travel; beaten entries and fights the sim loses are dropped."""
    out = []
    for e in ledger.entries(map_id):
        if e.state == "beaten":
            continue
        margin = _margin(party_now, list(e.mons), kb)
        if margin is None or margin < ENGAGE_MARGIN:
            continue
        xp = trainer_xp(e.mons, base_exp)
        prize = items_catalog.trainer_prize(cat, e.cls, e.party) if cat else None
        steps = PRIOR_BATTLE_STEPS + _travel(spots, e.x, e.y)
        value = xp + (prize or 0) * YEN_PER_XP
        out.append(TrainerGrind(e, xp, prize, steps, value / steps if steps else 0.0, margin, value))
    return sorted(out, key=lambda g: -g.xp_per_step)[:top]
