"""Catch plan: ranked "catch species S on map M" actions.

Every candidate from team_value.candidates_for is scored by team_value.member_value (boss gain + Pokedex
progress + the catcher role - training cost); each wild one becomes an action whose ``steps`` charge for the
detour, the expected grass steps to meet the species and the ball throws, so ``score`` = value per step is a
cost-efficiency ranking. Cheap new species with no boss value are first-class: the Pokedex term alone keeps
them in the plan when they are nearby, which is how the dex objective gets trained "along the way".

Pure: tables are passed in. Balls are never planned beyond ``budget.spendable`` (the reserve and the potion
floor are untouched); buying stays with the existing Restock behaviour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pokeagent.explorer import restock
from pokeagent.explorer.economy import budget
from pokeagent.knowledge import catch_math
from pokeagent.knowledge.encounters import map_name, slot_chances, species_on
from pokeagent.knowledge.party import species_row
from pokeagent.knowledge.team_value import BOSS_HORIZON, MemberValue, candidates_for, member_value

TEAM_SIZE = 6
PLAN_HP_FRACTION = 0.35        # the weaken target the plan assumes a throw happens at (catch_policy.WEAKEN_TARGET)
BALL_MARGIN = 2                # spare balls on top of the expected need
STEPS_PER_BALL = 20            # presses spent on one throw (weaken + ITEM menu); untuned
MAP_DISTANCE_FALLBACK = 12     # steps per map-id of distance when the learned graph has no path (|map id difference|)
RISK_LEVEL_MARGIN = 4          # a map whose strongest wild level exceeds the lead level by more than this is skipped (no-blackout run)
CHEAP_STEPS = 600              # an action at or under this many steps is "cheap" (new-species-here actions are always kept up to this)
FIGHT_STEPS = 40               # presses a training fight costs (the grind atlas's prior); untuned


@dataclass(frozen=True)
class CatchAction:
    species: str
    map: int
    name: str
    levels: tuple[int, int]
    chance: float
    rate: int
    value: float
    steps: float
    score: float
    balls: int
    blocked: str          # "" when doable now, else the reason ("no balls" ...)
    detour: float
    member: MemberValue


def p_catch(catch_rate: int) -> float:
    """Catch chance of one Poke Ball on a target weakened to PLAN_HP_FRACTION (knowledge.catch_math's formula)."""
    return catch_math.p_catch(catch_rate, hp=round(PLAN_HP_FRACTION * 100), hp_max=100)


def expected_balls(catch_rate: int) -> int:
    """Balls one catch is expected to need, plus the spare margin."""
    throws = catch_math.expected_throws(p_catch(catch_rate))
    return (math.ceil(throws) if math.isfinite(throws) else 999) + BALL_MARGIN


def map_prior_xp(row: dict, base_exp: dict) -> float:
    """Expected XP per wild encounter on a map's grass row (grind.atlas.prior_xp; re-exported so callers outside
    the knowledge layer need no grind import)."""
    from pokeagent.grind.atlas import prior_xp
    return prior_xp(row, base_exp)


def _xp(xp_for_map, m: int) -> float | None:
    if not m or xp_for_map is None:
        return None
    return xp_for_map(m) if callable(xp_for_map) else (xp_for_map or {}).get(m)


def plan_catches(party, here_map, goals, money, balls, owned_count, bosses, wild_by_map, known_maps, lead_level,
                 *, distance=None, magikarp_level=None, xp_for_map=None, owned_species=(), kb=None) -> list[CatchAction]:
    """The ranked catch actions, best ``score`` first (then ``value``, then the lower map id). A party of
    TEAM_SIZE returns [] (PC deposit/withdraw is out of scope: the plan stops at 6). ``bosses`` =
    [(label, [(level, species)])] for the next BOSS_HORIZON boss goals not yet met, built by the caller."""
    if len(party or ()) >= TEAM_SIZE:
        return []
    dist = distance or (lambda a, b: abs(int(a) - int(b)) * MAP_DISTANCE_FALLBACK)
    kb2 = {**(kb or {}), "wild_by_map": wild_by_map}
    known = {int(m) for m in (known_maps or ())}
    maps = [int(m) for m in (wild_by_map or {}) if int(m) in known or dist(here_map, int(m)) <= CHEAP_STEPS]
    maps = [m for m in maps if max((hi for _, hi, _ in species_on(m, kb2).values()), default=0)
            <= lead_level + RISK_LEVEL_MARGIN]
    spend = budget.spendable(goals or {}, money or 0)
    price = restock.ball_price()
    owned = set(owned_species or ())
    has_magikarp = any(c.name == "MAGIKARP" for c in party or ())
    out: list[CatchAction] = []
    for cand in candidates_for(party, wild_by_map, maps, magikarp_level, kb2):
        if cand.source == "magikarp" and not has_magikarp:
            continue  # a Magikarp we do not own is not a plan action (buying one is Restock's job)
        if cand.species in owned and cand.source.startswith("wild:"):
            continue  # an owned species is not a catch target
        m = int(cand.source.split(":", 1)[1]) if cand.source.startswith("wild:") else 0
        member = member_value(cand, party, bosses, xp_per_fight=_xp(xp_for_map, m),
                              owned_species=owned, owned_count=owned_count, kb=kb2)
        if member.value <= 0:
            continue
        row = (wild_by_map or {}).get(m) or (wild_by_map or {}).get(str(m)) or {}
        grass = row.get("grass") or []
        slots = [i for i, (_, n) in enumerate(grass) if n == cand.species]
        if m and not slots:
            continue
        chance = sum(slot_chances()[i] for i in slots)
        levels = (min(grass[i][0] for i in slots), max(grass[i][0] for i in slots)) if slots else (cand.level, cand.level)
        catch_rate = int((species_row(cand.species, kb2) or {}).get("catch_rate", 0) or 0)
        can_buy = spend // price if price else 0
        blocked = "no balls" if balls == 0 and can_buy < expected_balls(catch_rate) else ""
        planned_balls = min(expected_balls(catch_rate), balls + can_buy) if m else 0
        detour = dist(here_map, m) if m else 0.0
        steps = (detour + 256 / max(row.get("grass_rate") or 1, 1) / max(chance, 1e-6) + planned_balls * STEPS_PER_BALL
                 if m else max(member.fights, 1) * FIGHT_STEPS)
        score = member.value / max(steps, 1.0) * 1000
        out.append(CatchAction(cand.species, m, map_name(m) if m else "", levels, round(chance, 3),
                               int(row.get("grass_rate") or 0), member.value, round(steps, 1), round(score, 2),
                               planned_balls, blocked, round(detour, 1), member))
    out.sort(key=lambda a: (-a.score, -a.value, a.map))
    return out
