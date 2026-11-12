"""Party readiness: can OUR party beat a boss's party, and at what lead level? (Robert 2026-11-05: variable level
requirements based on the current party.)

Each duel is simulated with the Gen 1 damage formula (real stats and known moves for us, ROM base stats and learnset moves
for them, the ROM type chart): who moves first, how many turns each side needs. The party fight picks, for every enemy mon,
the switch-in with the best remaining HP. score = HP fraction left on the mons that fought (negative = enemy left when we lose).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from pokeagent.knowledge.damage import PHYSICAL, expected_damage, type_mult
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.moves import effect_of, fixed_of
from pokeagent.knowledge.party import Combatant, at_level, trainer_mon

MARGIN = 0.30             # remaining HP fraction wanted on the mons that fought
MAX_LEVEL, MAX_TURNS = 70, 80

TEAM_GAP = 6               # a useful second member is within this many levels of the lead
LEAD_HURT = 0.5            # the sim starts the lead at this fraction of its HP: the fight after the lead is hurt or faints
TEAM_MIN = 2               # members that must be useful before a boss (lead + one)


@dataclass(frozen=True)
class Readiness:
    ready: bool
    required: int             # lowest lead level that wins with margin (the current level when already ready)
    score: float
    lead: str
    text: str                 # the logged decision


@dataclass(frozen=True)
class MemberNeed:
    slot: int
    name: str
    level: int
    target: int
    useful: bool


@dataclass(frozen=True)
class TeamReadiness:
    ready: bool
    lead: Readiness | None        # the existing lead verdict from assess()
    members: tuple[MemberNeed, ...]
    weakest: MemberNeed | None    # the useful-member shortfall to fix first (lowest level among those below target); None when ready
    text: str                     # the logged decision


def _chart(kb) -> dict:
    return {(a, d): e for a, d, e in table(kb, "type_chart")}


def _move(name: str, moves: dict) -> dict | None:
    return next((m for m in moves.values() if m["name"] == name), None)


def best_move(att: Combatant, dfn: Combatant, chart: dict, moves: dict) -> tuple[float, str]:
    """(expected damage per turn, move name) of the best hit `att` knows against `dfn`; (0, "") when nothing damages."""
    best = (0.0, "")
    for name in att.moves:
        mv = _move(name, moves)
        if not mv or mv["power"] <= 0:
            continue
        eff = type_mult(chart, mv["type"], list(dfn.types))
        fixed = fixed_of(mv)
        if fixed:
            d = float({"level": att.level, "half": dfn.hp // 2, "20": 20, "40": 40}[fixed]) * (eff > 0)
        else:
            phys = mv["type"] in PHYSICAL
            d = expected_damage(att.level, mv["power"], att.stats[0] if phys else att.stats[3],
                                dfn.stats[1] if phys else dfn.stats[3], stab=mv["type"] in att.types, eff=eff)
            e = effect_of(mv)
            if e:
                d *= e.hits * (0.5 if e.charge or e.recharge else 1.0) * (0.0 if e.faints else 1.0)
        d *= mv["accuracy"]
        if d > best[0]:
            best = (d, name)
    return best


def duel(a: Combatant, ahp: float, b: Combatant, bhp: float, chart: dict, moves: dict) -> tuple[float, float]:
    """Fight a vs b to the end; returns (a's HP left, b's HP left). The faster mon hits first; ties go to b (cautious)."""
    da, db = best_move(a, b, chart, moves)[0], best_move(b, a, chart, moves)[0]
    order = (0, 1) if a.stats[2] > b.stats[2] else (1, 0)
    for _ in range(MAX_TURNS):
        for who in order:
            if who == 0:
                bhp -= da
            else:
                ahp -= db
            if ahp <= 0 or bhp <= 0:
                return max(ahp, 0.0), max(bhp, 0.0)
    return ahp, bhp


def fight(ours: list[Combatant], theirs: list[Combatant], chart: dict, moves: dict) -> float:
    """Best-switch party fight. >= 0: every enemy down, HP fraction left on the mons that fought;
    < 0: we lose, minus the number of enemy mons (fractions) still standing."""
    hp = [float(c.hp) for c in ours]
    used: set[int] = set()
    for n, foe in enumerate(theirs):
        fhp = float(foe.hp)
        while fhp > 0:
            alive = [i for i in range(len(ours)) if hp[i] > 0]
            if not alive:
                return -(fhp / foe.hp + len(theirs) - n - 1)

            def outcome(i):
                a_left, f_left = duel(ours[i], hp[i], foe, fhp, chart, moves)
                return (f_left <= 0, a_left / ours[i].hp if f_left <= 0 else -f_left)

            pick = max(alive, key=outcome)
            before = (hp[pick], fhp)
            hp[pick], fhp = duel(ours[pick], hp[pick], foe, fhp, chart, moves)
            used.add(pick)
            if (hp[pick], fhp) == before:      # nobody can hurt anybody: a stalemate is not a win
                return -(fhp / foe.hp + len(theirs) - n - 1)
    return sum(hp[i] for i in used) / sum(ours[i].hp for i in used)


def matchup_text(c: Combatant, foe: Combatant, chart: dict, moves: dict) -> str:
    """'Squirtle L11 WATER x4 vs ROCK/GROUND' - our lead's best move against their first mon."""
    mv = _move(best_move(c, foe, chart, moves)[1], moves)
    if not mv:
        return f"{c.name} L{c.level} no damaging move vs {'/'.join(foe.types)}"
    return f"{c.name} L{c.level} {mv['type']} x{type_mult(chart, mv['type'], list(foe.types)):g} vs {'/'.join(foe.types)}"


def assess(party: list[Combatant], boss: list[tuple[int, str]], label: str, kb: dict | None = None,
           margin: float = MARGIN) -> Readiness | None:
    """Readiness of `party` against `boss` ([(level, species)]); None when data is missing (caller falls back to its table).
    `margin` is the HP fraction demanded on the mons that fought (MARGIN by default; the blackout tax raises it per stage)."""
    theirs = [m for lv, n in boss if (m := trainer_mon(n, lv, kb))]
    moves = table(kb, "moves")
    if not party or not boss or len(theirs) != len(boss) or not moves:
        return None
    chart = _chart(kb)
    score = fight(party, theirs, chart, moves)
    lead, ready = party[0], score >= margin
    required = lead.level if ready else next(
        (L for L in range(lead.level + 1, MAX_LEVEL + 1)
         if fight([at_level(lead, L, kb), *party[1:]], theirs, chart, moves) >= margin), MAX_LEVEL)
    note = matchup_text(lead, theirs[0], chart, moves)
    text = f"ready vs {label}: {note} -> ok" if ready else f"train to L{required}: {note}"
    return Readiness(ready, required, round(score, 2), lead.name, text)


def team_readiness(party: list[Combatant], boss: list[tuple[int, str]], label: str,
                   kb: dict | None = None) -> TeamReadiness | None:
    """The whole party judged against `boss` (``[(level, species)]``), Magikarp INCLUDED in slot order.

    - ``None`` when ``assess`` would return ``None`` (missing data): empty party or boss, unknown species, no move table.
    - Lead verdict: ``lead = assess(party_without_trainee, ...)`` exactly as the lead-centric check does today, so the
      existing lead target is unchanged (the Magikarp trainee never fights a boss).
    - Team verdict: the same fight simulated with the lead starting at ``LEAD_HURT`` of its HP - "the fight after the
      lead is hurt or faints". The other members join at their CURRENT level; a MAGIKARP counts as the GYARADOS it
      becomes only once its level is >= EVOLVE_LEVEL, below that it fights as itself.
    - Per non-lead member ``target`` = ``max(lead.level - TEAM_GAP, sim_needed)`` capped at ``lead.level`` (and at
      least EVOLVE_LEVEL for a Magikarp, which is judged as ``trainer_mon("GYARADOS", max(level, EVOLVE_LEVEL))`` for
      the after-training search). ``sim_needed`` is the member's own level when the hurt-lead sim already passes,
      else the lowest level in current+1 .. MAX_LEVEL at which that member (``at_level``, or the Gyarados projection
      for a Magikarp) makes it pass with the other members unchanged; ``lead.level`` when no level passes.
      ``useful`` = ``level >= target``.
    - ``ready`` = the lead verdict is ready AND the hurt-lead sim passes AND the party has TEAM_MIN members (a one-mon
      party: not ready, ``weakest`` is None, the text says "no second member"). The sim already sends in the best
      switch-in per enemy mon, so a weak bench member the fight never uses cannot block a win (Misty 2026-11-12:
      KAKUNA L4 held a lead L25 outside the gym for 6,000 steps); ``useful`` only steers which member to train.
    - ``weakest`` = the not-useful non-lead member with the lowest level (ties: lowest slot)."""
    from pokeagent.magikarp import EVOLVE_LEVEL  # deferred: keep this pure module free of the emulator import
    theirs = [m for lv, n in boss if (m := trainer_mon(n, lv, kb))]
    moves = table(kb, "moves")
    if not theirs or not moves or not any(c.name != "MAGIKARP" for c in party):
        return None
    chart = _chart(kb)
    # The lead is the best opener, NOT whoever happens to sit in slot 0: judging slot 0 made a reorder flip the
    # verdict ("raise CHARMANDER to L18" vs "lead needs L27 (lead L9)" for PIDGEY; run explore-20261112-072650).
    lead_i = max((i for i, c in enumerate(party) if c.name != "MAGIKARP"),
                 key=lambda i: (best_move(party[i], theirs[0], chart, moves)[0] / max(theirs[0].hp, 1), party[i].level, -i))
    fighters = [party[lead_i]] + [c for i, c in enumerate(party) if i != lead_i and c.name != "MAGIKARP"]
    lead = assess(fighters, boss, label, kb)
    if lead is None:
        return None
    lead_c = party[lead_i]
    hurt = replace(lead_c, hp=int(lead_c.hp * LEAD_HURT))
    others = [(i, c) for i, c in enumerate(party) if i != lead_i]

    def grown(c: Combatant, level: int) -> Combatant:
        """`c` trained to `level`: a Magikarp is judged as the GYARADOS it becomes (EVOLVE_LEVEL or later)."""
        if c.name == "MAGIKARP":
            g = trainer_mon("GYARADOS", max(level, EVOLVE_LEVEL), kb)
            if g is not None:
                return g
        return at_level(c, level, kb)

    def now(c: Combatant) -> Combatant:
        """`c` as it fights today: only an evolved (>= EVOLVE_LEVEL) Magikarp counts as its GYARADOS."""
        return grown(c, c.level) if c.name == "MAGIKARP" and c.level >= EVOLVE_LEVEL else c

    def hurt_sim(at: tuple[int, int] | None = None) -> float:
        """The hurt-lead fight; `at` = (slot, level) re-levels one member for the sim_needed search."""
        return fight([hurt] + [grown(c, at[1]) if at and i == at[0] else now(c) for i, c in others],
                     theirs, chart, moves)

    def sim_needed(i: int, c: Combatant) -> int:
        """The member's own level when the current sim passes, else the lowest level in current+1..MAX_LEVEL that does."""
        if hurt_sim() >= MARGIN:
            return c.level
        return next((L for L in range(c.level + 1, MAX_LEVEL + 1) if hurt_sim((i, L)) >= MARGIN), lead_c.level)

    rows = [MemberNeed(lead_i, lead_c.name, lead_c.level, lead_c.level, lead.ready)]
    for i, c in others:
        floor = EVOLVE_LEVEL if c.name == "MAGIKARP" else 0
        target = min(lead_c.level, max(lead_c.level - TEAM_GAP, floor, sim_needed(i, c)))
        rows.append(MemberNeed(i, c.name, c.level, target, c.level >= target))
    useful = sum(r.useful for r in rows)
    ready = lead.ready and hurt_sim() >= MARGIN and len(rows) >= TEAM_MIN
    weakest = None if ready else min((r for r in rows if r.slot != lead_i and not r.useful),
                                     key=lambda r: (r.level, r.slot), default=None)
    if ready:
        text = f"team ready vs {label}: lead L{lead_c.level}, {useful}/{len(rows)} useful"
    elif len(rows) < TEAM_MIN:
        text = f"team not ready vs {label}: no second member (lead L{lead_c.level})"
    elif weakest is not None:
        text = f"team not ready vs {label}: {weakest.name} L{weakest.level} -> L{weakest.target} (lead L{lead_c.level})"
    else:
        why = f"lead needs L{lead.required}" if not lead.ready else "the hurt lead loses"
        text = f"team not ready vs {label}: {why} (lead L{lead_c.level})"
    return TeamReadiness(ready, lead, tuple(rows), weakest, text)
