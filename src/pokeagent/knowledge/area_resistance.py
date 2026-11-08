"""The party's type-chart margin against a whole area's trainer set - report only (no behaviour reads
this; Team_Builder_V2's team_value may import it later). resistance() = one readiness.fight per ROM
party plus the move types that hit ours super-effectively.
"""
from __future__ import annotations

from pokeagent.knowledge import readiness
from pokeagent.knowledge.damage import type_mult
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant, trainer_mon


def _move_types(names, moves: dict) -> list[str]:
    out = []
    for name in names:
        mv = next((m for m in moves.values() if m.get("name") == name), None)
        if mv and mv.get("type") and mv["type"] not in out:
            out.append(mv["type"])
    return out


def _weak_to(party: list[Combatant], theirs: list[Combatant], moves: dict, chart: dict) -> list[str]:
    """Enemy move types that hit SOME member of ours super-effectively, worst multiplier first."""
    mults: dict[str, float] = {}
    for foe in theirs:
        for mt in _move_types(foe.moves, moves):
            for c in party:
                m = type_mult(chart, mt, list(c.types))
                if m > 1.0 and m > mults.get(mt, 0.0):
                    mults[mt] = m
    return sorted(mults, key=lambda t: -mults[t])


def _worst(party: list[Combatant], theirs: list[Combatant], chart: dict, moves: dict) -> str | None:
    """The member least able to solo their party: per-enemy duels, -1 for a loss, HP fraction for a win."""
    worst = (None, float("inf"))
    for c in party:
        score = 0.0
        for foe in theirs:
            a, f = readiness.duel(c, float(c.hp), foe, float(foe.hp), chart, moves)
            score += a / c.hp if f <= 0 and c.hp else -1.0
        if score < worst[1]:
            worst = (c.name, score)
    return worst[0]


def resistance(party: list[Combatant], trainers: list[list[tuple[int, str]]], chart, moves, kb=None) -> dict:
    """Per trainer ``{"party", "margin", "worst_member", "weak_to"}`` plus ``area_margin`` (min over the
    set), ``mean_margin`` and the union ``weak_to``. ``{}`` on empty inputs."""
    if not party or not trainers:
        return {}
    moves = moves or table(kb, "moves")
    chart = chart or {(a, d): e for a, d, e in table(kb, "type_chart")}
    per, margins, weak = [], [], {}
    for mons in trainers:
        theirs = [m for lv, n in mons if (m := trainer_mon(n, lv, kb))]
        if not theirs or len(theirs) != len(mons) or not moves:
            per.append({"party": [list(p) for p in mons], "margin": None, "worst_member": None, "weak_to": []})
            continue
        w = _weak_to(party, theirs, moves, chart)
        for t in w:
            weak[t] = weak.get(t, 0) + 1
        margin = readiness.fight(list(party), theirs, chart, moves)
        margins.append(margin)
        per.append({"party": [list(p) for p in mons], "margin": round(margin, 2),
                    "worst_member": _worst(party, theirs, chart, moves), "weak_to": w})
    return {"trainers": per,
            "area_margin": round(min(margins), 2) if margins else None,
            "mean_margin": round(sum(margins) / len(margins), 2) if margins else None,
            "weak_to": sorted(weak, key=lambda t: -weak[t])}
