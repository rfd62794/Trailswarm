"""after_victory_rules: the pure push / potion / heal / continue decision after a trainer win.

``party_now`` is our party as it is NOW (each Combatant's ``hp`` holds its CURRENT hp; the max is recovered
from its species row + DVs/stat-exp, the same maths knowledge.party uses). ``remaining`` is the not-yet-beaten
trainers' parties in path order ([(level, species)] each); ``walk`` is outside_use.walk_to_center's
(frames, grass_tiles, center_map) or None. Missing data (no kb tables, an unknown species) always answers
``continue`` - the decision never blocks the route.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer.economy import heal_items
from pokeagent.explorer.economy.outside_use import MIN_MISSING, potion_beats_walk
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant, _stats, species_row, trainer_mon
from pokeagent.knowledge.readiness import MARGIN, _chart, fight

PUSH_MARGIN = MARGIN           # fight() score the NEXT trainer must clear with the party as it is now (0.30)
PUSH_MIN_LEAD_HP = 0.35        # never push on with the lead below this HP fraction (untuned first value)
PUSH_MIN_ALIVE = 2             # ... and at least this many members above 0 HP (a party of 1: 1) (untuned)
HEAL_WALK_MAX_FRAMES = 4000    # a Pokecenter round trip above this many frames is "too far" (untuned)
NEAR_WALK_FRAMES = 1200        # a Pokecenter this close (about 75 steps) is cheap insurance: push needs a healthier party
NEAR_MIN_LEAD_HP = 0.60        # ... lead at least this HP fraction (Robert 2026-11-12: pushed on at 63% lead / 42% party) (untuned)
NEAR_MIN_PARTY_HP = 0.55       # ... and the whole party at least this (untuned)
LOOKAHEAD = 2                  # how many remaining trainers on the path are simulated (next decides, second warns) (untuned)


@dataclass(frozen=True)
class VictoryDecision:
    action: str                # "push" | "potion" | "heal" | "continue"
    next_trainer: str          # e.g. "16 PIDGEY, 16 NIDORAN(F)" or "" when none left
    margin: float | None       # fight() score vs the next trainer (None when unknown)
    hp_frac: float
    lead_hp_frac: float
    alive: int
    why: str


def _max_hp(c: Combatant, kb) -> int:
    row = species_row(c.name, kb)
    return _stats(row, c.level, c.dv, c.sexp)[0] if row else c.hp


def _label(mons: list) -> str:
    return ", ".join(f"{lv} {n}" for lv, n in mons)


def decide(party_now: list, remaining: list, bag: dict, walk, kb=None) -> VictoryDecision:
    hp_frac, lead_hp_frac, alive = 0.0, 0.0, 0
    mx_all, hp_all = 0, 0
    for c in party_now:
        mx = _max_hp(c, kb)
        mx_all += mx
        hp_all += c.hp
    hp_frac = hp_all / mx_all if mx_all else 0.0
    if party_now:
        lead_hp_frac = party_now[0].hp / (_max_hp(party_now[0], kb) or 1)
    alive = sum(1 for c in party_now if c.hp > 0)
    if not remaining:
        return VictoryDecision("continue", "", None, hp_frac, lead_hp_frac, alive, "path clear: carry on")
    mons = remaining[0]
    theirs = [m for lv, n in mons if (m := trainer_mon(n, lv, kb))]
    moves = table(kb, "moves")
    if not party_now or len(theirs) != len(mons) or not moves:
        return VictoryDecision("continue", _label(mons), None, hp_frac, lead_hp_frac, alive, "no sim data")
    chart = _chart(kb)
    score = fight(party_now, theirs, chart, moves)
    warn = ""
    if len(remaining) >= LOOKAHEAD:  # the next one decides; the LOOKAHEAD-th warns
        theirs2 = [m for lv, n in remaining[LOOKAHEAD - 1] if (m := trainer_mon(n, lv, kb))]
        if len(theirs2) == len(remaining[LOOKAHEAD - 1]):
            s2 = fight(party_now, theirs2, chart, moves)
            warn = f"; next-but-one {s2:+.2f}" if s2 < PUSH_MARGIN else ""
    near = walk is not None and walk[0] <= NEAR_WALK_FRAMES
    hurt_near = near and (lead_hp_frac < NEAR_MIN_LEAD_HP or hp_frac < NEAR_MIN_PARTY_HP)  # a short walk: retreat earlier
    if (score >= PUSH_MARGIN and lead_hp_frac >= PUSH_MIN_LEAD_HP and alive >= min(PUSH_MIN_ALIVE, len(party_now))
            and not hurt_near):
        return VictoryDecision("push", _label(mons), score, hp_frac, lead_hp_frac, alive,
                               f"margin {score:+.2f} clears {PUSH_MARGIN}{warn}")
    lead_hp = party_now[0].hp
    lead_mx = _max_hp(party_now[0], kb)
    if (heal_items.heal_count(bag) > 0 and lead_mx - lead_hp >= MIN_MISSING
            and (walk is None or potion_beats_walk(walk[0], walk[1], lead_hp, lead_mx))):
        return VictoryDecision("potion", _label(mons), score, hp_frac, lead_hp_frac, alive,
                               f"field potion is the cheaper heal{warn}")
    if walk is not None and walk[0] <= HEAL_WALK_MAX_FRAMES:
        return VictoryDecision("heal", _label(mons), score, hp_frac, lead_hp_frac, alive,
                               f"Pokecenter walk {walk[0]:.0f} frames{warn}")
    if score >= 0:  # (reached only with no walk / too far: hurt_near always found the "heal" branch above)
        return VictoryDecision("push", _label(mons), score, hp_frac, lead_hp_frac, alive,
                               f"no cheaper heal; thin margin{warn}")
    return VictoryDecision("continue", _label(mons), score, hp_frac, lead_hp_frac, alive,
                           "cannot win the next trainer and nowhere to heal: procedure/exploration decides")
