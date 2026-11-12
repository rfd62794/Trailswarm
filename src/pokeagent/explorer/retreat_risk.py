"""retreat_risk: should the party walk back to a Pokecenter BEFORE the next fight, judged by what the next fight costs?

Robert (2026-11-12, live run): the explorer pushed on at 40-60% party HP (17 trainer decisions "push", 41 battles, 9 started
below half HP) and only healed once a member was already down. The old triggers were HP-fraction gates inside goal stages
(planner.py), poison (status_care) and a trainer win (after_victory). A wild encounter on the road asked nothing.

The rule here is risk-based and pure: the foe is the strongest wild mon of the current map's grass (knowledge.encounters
.species_on, chance-weighted out below MIN_CHANCE); the fighter is the first living party member at its CURRENT hp;
``readiness.duel`` says how much HP it keeps. Retreat when it keeps less than ``floor(walk_frames)``: the floor RISES the
nearer the nurse is (a short walk is cheap insurance) and falls when she is far (a long trek costs more than the risk).
No wild table for the map: the fighter's own HP fraction stands in for the duel result.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from pokeagent.knowledge import encounters
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant, our_party, species_row, trainer_mon, _stats
from pokeagent.knowledge.readiness import _chart, duel
from pokeagent.ramstructs import read_party

FLOOR_NEAR, FLOOR_FAR = 0.55, 0.30      # HP fraction the fighter must keep after the worst likely wild duel (untuned)
NEAR_FRAMES, FAR_FRAMES = 700, 3000     # walk to the nurse: at or below NEAR the floor is FLOOR_NEAR, at FAR it is FLOOR_FAR
MAX_WALK_FRAMES = 4000                  # a nurse farther than this is never worth a retreat (same cap as after_victory)
PARTY_FLOOR = 0.35                      # whole-party HP fraction below which a known nurse is always walked to (untuned)
MIN_CHANCE = 0.05                       # a wild species rarer than this per encounter does not set the risk


@dataclass(frozen=True)
class Verdict:
    retreat: bool
    why: str


def party_now(emu) -> list[Combatant]:
    """Our party as Combatants with each member's hp replaced by its CURRENT hp (same slot filter our_party uses)."""
    names = table(None, "name_of_internal")
    mons = [m for m in read_party(emu) if m.level and species_row(names.get(str(m.species), ""), None) is not None]
    return [replace(c, hp=mons[i].hp) for i, c in enumerate(our_party(emu)) if i < len(mons)]


def floor_for(walk_frames: float) -> float:
    """The HP fraction to keep: FLOOR_NEAR on a short walk, easing down to FLOOR_FAR on a long one."""
    if walk_frames <= NEAR_FRAMES:
        return FLOOR_NEAR
    if walk_frames >= FAR_FRAMES:
        return FLOOR_FAR
    t = (walk_frames - NEAR_FRAMES) / (FAR_FRAMES - NEAR_FRAMES)
    return FLOOR_NEAR + t * (FLOOR_FAR - FLOOR_NEAR)


def _max_hp(c: Combatant, kb) -> int:
    row = species_row(c.name, kb)
    return _stats(row, c.level, c.dv, c.sexp)[0] if row else max(c.hp, 1)


def _worst_wild(wild: dict, kb) -> list[Combatant]:
    """The wild foes that set the risk: every species at least MIN_CHANCE likely, at its top level there."""
    return [f for n, (_, hi, ch) in wild.items() if ch >= MIN_CHANCE and (f := trainer_mon(n, hi, kb))]


def assess(party: list[Combatant], wild: dict, walk_frames: float | None, kb=None, fighter_idx: int = 0) -> Verdict:
    """Retreat verdict. ``party``: current-hp Combatants in party order; ``wild``: encounters.species_on(map);
    ``walk_frames``: frames to the nearest known Pokecenter (None = unknown: never retreat);
    ``fighter_idx``: the party slot that does the fighting (cave_topup.fighter_slot: not the Magikarp in training)."""
    if not party or walk_frames is None or walk_frames > MAX_WALK_FRAMES:
        return Verdict(False, "no party or no reachable Pokecenter")
    total_hp = sum(c.hp for c in party)
    total_max = sum(_max_hp(c, kb) for c in party) or 1
    if total_hp / total_max < PARTY_FLOOR:
        return Verdict(True, f"party at {total_hp / total_max:.0%}, nurse {walk_frames:.0f} frames away")
    fighter = party[fighter_idx] if fighter_idx < len(party) and party[fighter_idx].hp > 0 else next((c for c in party if c.hp > 0), None)
    if fighter is None:
        return Verdict(True, "everyone has fainted")
    floor = floor_for(walk_frames)
    mx = _max_hp(fighter, kb)
    left = fighter.hp / mx
    foes = _worst_wild(wild, kb)
    if foes and table(kb, "moves"):
        chart, moves = _chart(kb), table(kb, "moves")
        left = min(duel(fighter, float(fighter.hp), f, float(f.hp), chart, moves)[0] / mx for f in foes)
    if left < floor:
        return Verdict(True, f"{fighter.name} would keep {left:.0%} vs the worst wild fight here (floor {floor:.0%}, "
                             f"nurse {walk_frames:.0f} frames)")
    return Verdict(False, f"{fighter.name} keeps {left:.0%} (floor {floor:.0%})")
