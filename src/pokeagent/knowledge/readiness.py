"""Party readiness: can OUR party beat a boss's party, and at what lead level? (Robert 2026-11-05: variable level
requirements based on the current party.)

Each duel is simulated with the Gen 1 damage formula (real stats and known moves for us, ROM base stats and learnset moves
for them, the ROM type chart): who moves first, how many turns each side needs. The party fight picks, for every enemy mon,
the switch-in with the best remaining HP. score = HP fraction left on the mons that fought (negative = enemy left when we lose).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.knowledge.damage import PHYSICAL, expected_damage, type_mult
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.moves import effect_of, fixed_of
from pokeagent.knowledge.party import Combatant, at_level, trainer_mon

MARGIN = 0.30             # remaining HP fraction wanted on the mons that fought
MAX_LEVEL, MAX_TURNS = 70, 80


@dataclass(frozen=True)
class Readiness:
    ready: bool
    required: int             # lowest lead level that wins with margin (the current level when already ready)
    score: float
    lead: str
    text: str                 # the logged decision


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
