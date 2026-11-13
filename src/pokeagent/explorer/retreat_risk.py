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

SURVIVE_NEAR, SURVIVE_FAR = 0.15, 0.05  # HP fraction a party member must keep after the worst wild duel: a variance/crit cushion (untuned)
NEAR_FRAMES, FAR_FRAMES = 700, 3000     # walk to the nurse: at or below NEAR the margin is SURVIVE_NEAR, at FAR it is SURVIVE_FAR
MAX_WALK_FRAMES = 4000                  # a nurse farther than this is never worth a retreat (same cap as after_victory)
PARTY_FLOOR = 0.20                      # whole-party HP fraction below which a known nurse is always walked to (untuned)
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


def survive_margin(walk_frames: float) -> float:
    """The HP fraction a member must keep: SURVIVE_NEAR on a short walk, easing down to SURVIVE_FAR on a long one."""
    if walk_frames <= NEAR_FRAMES:
        return SURVIVE_NEAR
    if walk_frames >= FAR_FRAMES:
        return SURVIVE_FAR
    t = (walk_frames - NEAR_FRAMES) / (FAR_FRAMES - NEAR_FRAMES)
    return SURVIVE_NEAR + t * (SURVIVE_FAR - SURVIVE_NEAR)


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
    margin = survive_margin(walk_frames)
    order = _order(party, fighter_idx)
    if not order:
        return Verdict(True, "everyone has fainted")
    kept = _kept(order, wild, kb)
    fighter, left = kept[0]
    if left >= margin:
        return Verdict(False, f"{fighter.name} keeps {left:.0%} (margin {margin:.0%})")
    carrier = next(((c, k) for c, k in kept[1:] if k >= margin), None)
    if carrier:
        return Verdict(False, f"{fighter.name} would keep {left:.0%} but {carrier[0].name} would carry the fight "
                              f"({carrier[1]:.0%}, margin {margin:.0%})")
    best, bk = max(kept, key=lambda ck: ck[1])
    return Verdict(True, f"no party member keeps {margin:.0%} vs the worst wild fight here (best {best.name} {bk:.0%}, "
                         f"nurse {walk_frames:.0f} frames)")


def _order(party: list[Combatant], fighter_idx: int) -> list[Combatant]:
    """Living members, the designated fighter first (else the first living one), then the bench in party order."""
    living = [c for c in party if c.hp > 0]
    lead = party[fighter_idx] if fighter_idx < len(party) and party[fighter_idx].hp > 0 else None
    return ([lead] + [c for c in living if c is not lead]) if lead else living


def _kept(order: list[Combatant], wild: dict, kb) -> list[tuple[Combatant, float]]:
    """Each member's HP fraction left after the worst likely wild duel (no wild table/moves: its own HP fraction)."""
    foes, moves = _worst_wild(wild, kb), table(kb, "moves")
    out = []
    for c in order:
        mx = _max_hp(c, kb)
        left = c.hp / mx
        if foes and moves:
            chart = _chart(kb)
            left = min(duel(c, float(c.hp), f, float(f.hp), chart, moves)[0] / mx for f in foes)
        out.append((c, left))
    return out


def survives_next_wild(party: list[Combatant], wild: dict, kb=None, fighter_idx: int = 0, margin: float = SURVIVE_NEAR) -> bool:
    """True when some living member keeps >= margin after the worst wild duel (the same test as assess; no wild table -> own HP fraction)."""
    return any(k >= margin for _, k in _kept(_order(party, fighter_idx), wild, kb))


def party_survives(emu, map_id: int, kb=None) -> bool:
    """Emu adapter for the grind gates. Any fainted member -> False (routes to heal exactly as before)."""
    from pokeagent.explorer.behaviours.cave_topup import fighter_slot
    from pokeagent.party_view import read_party_view
    if read_party_view(emu).any_fainted:
        return False  # read straight from RAM: a member party_now skips (unknown species) still counts
    party = party_now(emu)
    if not party:  # species unreadable: the fighter's own HP fraction stands in
        from pokeagent.explorer.perceive import party_hp
        hp, mx = party_hp(emu)
        return not mx or hp / mx >= SURVIVE_NEAR
    if any(c.hp <= 0 for c in party):
        return False
    return survives_next_wild(party, encounters.species_on(map_id), kb, fighter_slot(emu))
