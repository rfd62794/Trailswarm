"""Training levels per campaign stage: a party readiness check, with one named table as the fallback.

Robert (2026-11-05): "We may have to look at variable Level Requirements based on Current Party." So the level wanted
before a stage is the lowest lead level at which OUR party (real stats, known moves, the type chart) beats the next boss's
party with margin (pokeagent.knowledge.readiness); a super-effective starter is ready earlier than a resisted one.
TRAIN_LEVEL_BY_GOAL is the fallback when the ROM tables or the party are missing; --train-level stays a hard floor.
"""
from __future__ import annotations

from pokeagent.explorer.world import DUNGEON_MAPS, SHIP_MAPS
from pokeagent.goals import GOALS
from pokeagent.knowledge import team_floor, team_plan, trainers
from pokeagent.knowledge.readiness import MARGIN, Readiness, TeamReadiness, assess, team_readiness

# The lead's level wanted BEFORE the goal on the left is attempted; it applies from the previous entry's goal until this one lands.
# (Robert, 2026-11-05: two blackouts in Mt Moon at level 8; Misty's Staryu/Starmie are L18/L21.)
TRAIN_LEVEL_BY_GOAL = {
    "beat_brock": 12, "to_mt_moon": 14, "beat_misty": 20,
    # FALLBACKS (2026-11-06): used only when the ROM trainer data or our party is missing; about the boss's top level, from
    # the ROM parties (S.S. Anne rival 20, Surge 24, Erika 29, tower rival 25, Koga 43, Silph rival 40, Sabrina 43,
    # Blaine 47, Giovanni 50, Route 22 rival 53, Lorelei 56, Bruno 58, Agatha 60, Lance 62, champion 65).
    "rival_ss_anne": 20, "beat_surge": 25, "beat_erika": 30, "rival_pokemon_tower": 26, "beat_koga": 42,
    "rival_silph": 38, "beat_sabrina": 42, "beat_blaine": 46, "beat_giovanni": 49, "rival_route22": 50,
    "beat_lorelei": 54, "beat_bruno": 56, "beat_agatha": 58, "beat_lance": 60, "beat_champion": 62}
BOSS_LABEL = {"beat_brock": "BROCK", "to_mt_moon": "MT MOON", "beat_misty": "MISTY", "rival_ss_anne": "RIVAL (S.S. ANNE)",
              "beat_surge": "LT.SURGE", "beat_erika": "ERIKA", "rival_pokemon_tower": "RIVAL (POKEMON TOWER)",
              "beat_koga": "KOGA", "rival_silph": "RIVAL (SILPH CO)", "beat_sabrina": "SABRINA", "beat_blaine": "BLAINE",
              "beat_giovanni": "GIOVANNI", "rival_route22": "RIVAL (ROUTE 22)", "beat_lorelei": "LORELEI",
              "beat_bruno": "BRUNO", "beat_agatha": "AGATHA", "beat_lance": "LANCE", "beat_champion": "CHAMPION"}
CAP_ABOVE_TABLE = 5
_cache: dict = {}
_tax: dict[str, float] = {}   # stage goal -> extra readiness margin learned from blackouts (knowledge.blackout_tax)


def set_blackout_tax(extras: dict[str, float]) -> None:
    """Replace the per-goal blackout-margin table ({} clears it). plan_goal feeds it from mem.data each step so
    every readiness_for caller - including ship_gate.under_level - sees the tax with no signature change."""
    global _tax
    _tax = dict(extras)


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
    margin = MARGIN + _tax.get(goal, 0.0)
    key = (goal, margin, tuple(party))
    if key not in _cache:
        boss = trainers.boss_party(goal, starter_names=[c.name for c in party]) or (trainers.strongest_on_mt_moon() if goal == "to_mt_moon" else [])
        _cache.clear() if len(_cache) > 64 else None
        _cache[key] = assess(party, boss, BOSS_LABEL[goal], margin=margin) if boss else None
    return _cache[key]


def team_for(goals: dict, party: list | None) -> TeamReadiness | None:
    """The WHOLE party (Magikarp included) vs the stage boss: the hurt-lead team verdict; None without data.
    Same boss lookup, label and cache as readiness_for - the team sim keeps the plain MARGIN (no blackout tax)."""
    goal = stage_goal(goals)
    if goal is None or not party:
        return None
    key = ("team", goal, tuple(party))
    if key not in _cache:
        boss = trainers.boss_party(goal, starter_names=[c.name for c in party]) or (trainers.strongest_on_mt_moon() if goal == "to_mt_moon" else [])
        _cache.clear() if len(_cache) > 64 else None
        _cache[key] = team_readiness(party, boss, BOSS_LABEL[goal]) if boss else None
    return _cache[key]


def boss_need_for(goals: dict, party: list | None) -> team_plan.Need | None:
    """The WHOLE party (Magikarp included) vs the stage boss: the team-level gate (knowledge.team_plan).
    Same boss lookup, label and cache as readiness_for/team_for; None without data."""
    goal = stage_goal(goals)
    if goal is None or not party:
        return None
    key = ("need", goal, tuple(party))
    if key not in _cache:
        boss = trainers.boss_party(goal, starter_names=[c.name for c in party]) or (trainers.strongest_on_mt_moon() if goal == "to_mt_moon" else [])
        _cache.clear() if len(_cache) > 64 else None
        _cache[key] = team_plan.boss_need(party, boss, None, BOSS_LABEL[goal]) if boss else None
    return _cache[key]


def floor_for(goals: dict, party: list | None) -> team_floor.Floor | None:
    """The stage's team level floor (knowledge.team_floor) for the whole party; None without data or a floor for the stage."""
    goal = stage_goal(goals)
    if goal is None or not party:
        return None
    key = ("floor", goal, tuple(party))
    if key not in _cache:
        boss = trainers.boss_party(goal, starter_names=[c.name for c in party])
        _cache.clear() if len(_cache) > 64 else None
        _cache[key] = team_floor.check(goal, party, boss) if boss else None
    return _cache[key]


def train_member_for(nv, team, floor=None) -> int | None:
    """The slot to train, agreeing with the gate hold (``not team_floor.ready(nv, floor)``): while the sim says not ready it
    is the member whose raise flips it (``raise_slot``), else the lead/fighter; when only the FLOOR fails it is the sendable
    member closest below the floor; with the gate open the hurt-lead sim's weakest steers."""
    if nv is not None and not nv.ready:
        raise_slot = getattr(nv, "raise_slot", None)
        return raise_slot if raise_slot is not None else getattr(nv, "lead_slot", None)
    if floor is not None and not floor.met and floor.target_slot is not None:
        return floor.target_slot
    return team.weakest.slot if team and team.weakest else None


def gate_state(ctx, goals: dict, party: list | None, nv, team) -> tuple[int | None, bool]:
    """(train_member, gate_ready): the ONE gym verdict plan_goal holds on and trains from. ready = the whole-party sim passes
    AND the checkpoint's team floor is met; the failing floor reason is logged once per change."""
    floor = floor_for(goals, party)
    ctx.__dict__["floor_unmet"] = floor is not None and not floor.met  # plan_goal's stall escape reads it (floor must hold)
    if floor is None or floor.met:
        ctx.floor_note = None  # met again: a later identical failure is logged afresh
    elif floor.text != ctx.floor_note:
        ctx.floor_note = floor.text
        ctx.log(f"[readiness] {floor.text}", "res")
    return train_member_for(nv, team, floor), team_floor.ready(nv, floor)


def under_level(goals: dict, party: list | None, floor: int = 0) -> tuple[int, int, int] | None:
    """(needed level, current level, gap) when the TEAM fails the next stage's verdict, else None.
    The gate judges the whole party: "under" whenever boss_need says not ready, whichever slot holds
    the strong mon (`current` is the level of the member the verdict would raise). One source for the
    planner log, the bandit's train point and the grind atlas: all three read required_level."""
    if not party:
        return None
    needed = required_level(goals, floor, party)[0]
    nv = boss_need_for(goals, party)
    if nv is not None:
        if nv.ready:
            fl = floor_for(goals, party)
            if fl is not None and not fl.met and fl.target_slot is not None:  # sim passes, the team floor does not
                return (fl.level, party[fl.target_slot].level, fl.level - party[fl.target_slot].level)
            return None
        i = nv.raise_slot if nv.raise_slot is not None else nv.lead_slot
        return (needed, party[i].level, needed - party[i].level)
    current = max(c.level for c in party)  # no sim data: the strongest member answers, not slot 0
    return (needed, current, needed - current) if current < needed else None


def under_level_note(goals: dict, party: list | None, floor: int = 0) -> str:
    """'under-level for beat_surge: need L25, have L21' (empty when ready), the planner's once-per-change log line."""
    gap = under_level(goals, party, floor)
    return f"under-level for {stage_goal(goals)}: need L{gap[0]}, have L{gap[1]}" if gap else ""


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
    table = TRAIN_LEVEL_BY_GOAL[goal]
    fighters = [c for c in (party or ()) if c.name != "MAGIKARP"] or list(party or ())
    verdict, nv = readiness_for(goals, fighters), boss_need_for(goals, party)
    sim_need = nv.need if nv is not None else (verdict.required if verdict else None)
    if sim_need is None:
        return max(table, floor), ""
    cap = table + CAP_ABOVE_TABLE
    note = f"clamp L{sim_need} -> L{cap} vs {BOSS_LABEL[goal]}: consider a counter catch" if sim_need > cap else ""
    return max(min(sim_need, cap), floor), note


def train_level_for(goals: dict, floor: int = 8, party: list | None = None) -> int:
    """Level wanted for the next unmet goal's stage (see required_level)."""
    return required_level(goals, floor, party)[0]


def gate_for(map_id: int, need: int) -> int:
    """The training level the planner may enforce on this map: none (0) inside a dungeon or aboard the S.S. Anne (no grass there;
    ship_gate walks an under-level agent off the ship), ``need`` elsewhere."""
    return 0 if map_id in DUNGEON_MAPS or map_id in SHIP_MAPS else need
