"""The catcher role: a low-level party member that can hurt a wild mon without wiping it.

HARD RULE (Robert, 2026-11-07): "a cheap low-level member only has value as the catcher if they can cause
damage. Magikarp does not apply without an attack to cause damage." So a Splash-only Magikarp does NOT
qualify, a status-only move set does NOT qualify (status is a bonus the catch policy spends, never the
qualification), and a mon whose every damaging move KOs the wild mon even at the minimum roll does NOT
qualify either - that is the overpower gate this module exists to answer.

``wild`` Combatants carry the HP the safe-hit check compares against (their current HP in a live battle,
their full HP for a route's species at its lowest level). ``chart`` is {(move type, def type): mult} and
``moves`` the kb moves table ({id: {name, type, power, accuracy, effect, ...}}); both pure inputs.
"""
from __future__ import annotations

from pokeagent.knowledge.damage import AVG_ROLL, CRIT_RATE, PHYSICAL, expected_damage, type_mult
from pokeagent.knowledge.party import Combatant

MIN_ROLL = 217 / 255 / AVG_ROLL     # scales an expected_damage (average roll) down to the minimum roll
CATCHER_BAND = 6                    # a "catcher" is a member at least this many levels below the lead; untuned


def _move_row(name: str, moves: dict) -> dict | None:
    return next((m for m in (moves or {}).values() if m.get("name") == name), None)


def _raw(att: Combatant, move: dict, dfn: Combatant, chart: dict) -> float:
    """expected_damage of ``move`` on ``dfn``; 0 for a non-damaging or ineffective move."""
    power = int(move.get("power", 0) or 0)
    eff = type_mult(chart, move.get("type", ""), list(dfn.types))
    phys = move.get("type", "") in PHYSICAL
    return expected_damage(att.level, power, att.stats[0] if phys else att.stats[3],
                           dfn.stats[1] if phys else dfn.stats[3], stab=move.get("type", "") in att.types, eff=eff)


def min_damage(att: Combatant, move: dict, dfn: Combatant, chart: dict) -> float:
    """expected_damage scaled to the minimum roll and without the crit bonus; 0 for a non-damaging move."""
    return _raw(att, move, dfn, chart) * MIN_ROLL / (1 + CRIT_RATE)


def max_damage(att: Combatant, move: dict, dfn: Combatant, chart: dict) -> float:
    """The roll-255 hit with no crit: expected_damage with the average-roll and crit folds divided out."""
    return _raw(att, move, dfn, chart) / AVG_ROLL / (1 + CRIT_RATE)


def safe_moves(att: Combatant, dfn: Combatant, chart: dict, moves: dict) -> list[str]:
    """The move names of ``att`` with 0 < min_damage < dfn.hp: a hit that cannot KO even at the min roll, and hurts."""
    out = []
    for name in att.moves:
        mv = _move_row(name, moves)
        if mv is not None and 0 < min_damage(att, mv, dfn, chart) < dfn.hp:
            out.append(name)
    return out


def qualifies(member: Combatant, wild: list[Combatant], chart: dict, moves: dict) -> bool:
    """True iff ``member`` has at least one safe move against EVERY wild mon in ``wild``."""
    return bool(wild) and all(safe_moves(member, w, chart, moves) for w in wild)


def catcher_slot(party: list[Combatant], wild: list[Combatant], chart: dict, moves: dict,
                 lead: int = 0) -> int | None:
    """Party index of the lowest-level qualifying member that is not ``lead``, else None."""
    best = None
    for i, m in enumerate(party or ()):
        if i == lead or not qualifies(m, wild, chart, moves):
            continue
        if best is None or m.level < party[best].level:
            best = i
    return best


def level_band_ok(party: list[Combatant], wild: list[Combatant], chart: dict, moves: dict,
                  band: int = CATCHER_BAND) -> bool:
    """True when a qualifying member within ``band`` levels BELOW the lead exists (party[0] is the lead)."""
    if not party:
        return False
    return any(m.level <= party[0].level - band and qualifies(m, wild, chart, moves) for m in party)
