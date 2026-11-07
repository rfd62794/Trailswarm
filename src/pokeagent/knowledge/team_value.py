"""Team value: what a candidate party member is worth.

value = boss contributions (the hurt-lead sim of knowledge.readiness) + Pokedex progress (a standing objective:
the next Oak's-aide gate is worth a share per missing species) + the ``catcher`` role (a low-level member that
can damage a wild mon without wiping it - Robert's "lower level last option for wild exploit") - training cost
(the fights needed to reach the level the sim wants).

Pure: no emulator, no RAM. The kb tables (species_by_dex, moves, type_chart, learnsets, wild_by_map) are passed
in. The kb has NO evolution table, so EVOLUTIONS is a small hand constant (Gen 1 level evolutions only, NOT
ROM-verified); stone and trade evolutions stay the base form. In-game trades: out of scope, no table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pokeagent.grind.xpmath import xp_needed
from pokeagent.knowledge.damage import AVG_ROLL, PHYSICAL, expected_damage, type_mult
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant, species_row, trainer_mon
from pokeagent.knowledge.readiness import LEAD_HURT, MAX_LEVEL, fight, team_readiness

# Gen 1 (pokered) level evolutions. The kb has no evolution table, so this is a constant; KEEP IT SMALL and
# note it is not ROM-verified.
EVOLUTIONS: dict[str, tuple[str, int]] = {
    "SQUIRTLE": ("WARTORTLE", 16), "WARTORTLE": ("BLASTOISE", 36),
    "BULBASAUR": ("IVYSAUR", 16), "IVYSAUR": ("VENUSAUR", 32),
    "CHARMANDER": ("CHARMELEON", 16), "CHARMELEON": ("CHARIZARD", 36),
    "MAGIKARP": ("GYARADOS", 20), "NIDORAN(M)": ("NIDORINO", 16), "NIDORAN(F)": ("NIDORINA", 16),
    "CATERPIE": ("METAPOD", 7), "METAPOD": ("BUTTERFREE", 10), "WEEDLE": ("KAKUNA", 7), "KAKUNA": ("BEEDRILL", 10),
    "ODDISH": ("GLOOM", 21), "PARAS": ("PARASECT", 24), "ABRA": ("KADABRA", 16),
}
BOSS_HORIZON = 6               # remaining bosses scored (beyond that a member is speculation); untuned
CONTRIB_MARGIN = 0.10          # a member also "contributes" when it raises the hurt-lead sim margin by at least this much; untuned
COST_PER_FIGHT = 0.01          # value units per training fight (100 fights = one boss contribution); untuned
XP_PER_FIGHT_FALLBACK = 40     # expected wild-fight XP when no map prior is available (roughly the Route 2-3 range)
TRAINEE_SHARE = 0.5            # a switched-out trainee earns this share of a fight's XP (Gen 1 splits experience)
MAGIKARP_START_LEVEL = 5       # ASSUMPTION (not verified): used only when no Magikarp is owned; an owned one uses its real level
DEX_GATES = (10, 30, 50)       # owned-count thresholds that unlock items (Oak's aides); ONLY 10 is recorded in campaign.json - the rest are to verify on the ROM
DEX_GATE_VALUE = 1.0           # value of reaching the next gate, in boss-contribution units, spread over the species still missing; untuned
DEX_FLOOR_VALUE = 0.05         # a new species with no gate in sight still counts a little (variety); untuned
CATCHER_BAND = 6               # a "catcher" is a member at least this many levels below the lead (the wild-exploit option); untuned
CATCHER_VALUE = 0.15           # value of adding a catcher when the party has none; untuned
MIN_ROLL = (217 / 255) / AVG_ROLL  # scales expected_damage (which uses the average roll) down to the minimum roll
GROWTHS = ("MEDIUM_FAST", "MEDIUM_SLOW", "FAST", "SLOW")


@dataclass(frozen=True)
class Candidate:
    species: str
    level: int                          # the level it is caught (or currently is) at
    source: str                         # "party-evolution" | "wild:<map id>" | "magikarp" | "catcher"


@dataclass(frozen=True)
class MemberValue:
    candidate: Candidate
    target_level: int | None            # the lowest level the sim needs for the team to be ready (None = never enough by MAX_LEVEL)
    contributes: tuple[str, ...]        # boss labels it contributes to
    gain: float
    fights: int
    cost: float
    dex: float
    catcher: float
    value: float                        # gain + dex + catcher - cost


def form_at(species: str, level: int) -> str:
    """The form a mon has at ``level``, following EVOLUTIONS (a species not in the table is itself)."""
    cur = species
    while (evo := EVOLUTIONS.get(cur)) is not None and level >= evo[1]:
        cur = evo[0]
    return cur


def _growth(species: str, kb) -> str:
    g = (species_row(species, kb) or {}).get("growth", "")
    return g if g in GROWTHS else "MEDIUM_SLOW"


def fights_to_reach(species: str, from_level: int, to_level: int | None, xp_per_fight: float | None,
                    kb=None, trainee: bool = False) -> int:
    """Wild fights needed to go from ``from_level`` to ``to_level`` at ``xp_per_fight`` XP each
    (XP_PER_FIGHT_FALLBACK when unknown; a trainee earns TRAINEE_SHARE of it)."""
    if to_level is None or to_level <= from_level:
        return 0
    xp = (xp_per_fight or XP_PER_FIGHT_FALLBACK) * (TRAINEE_SHARE if trainee else 1.0)
    return math.ceil(xp_needed(_growth(species, kb), from_level, to_level) / xp) if xp > 0 else 0


def pokedex_value(species: str, owned_count: int, owned_species=frozenset(), gates=DEX_GATES) -> float:
    """A new species' Pokedex worth: 0 when already owned; else DEX_FLOOR_VALUE plus a share of the next gate
    (DEX_GATE_VALUE spread over the species still missing to reach it). Past the last gate only the floor remains."""
    if species in owned_species:
        return 0.0
    nxt = next((g for g in gates if g > owned_count), None)
    return DEX_FLOOR_VALUE + (DEX_GATE_VALUE / (nxt - owned_count) if nxt is not None else 0.0)


def _move_row(name: str, moves_tbl: dict) -> dict | None:
    return next((m for m in moves_tbl.values() if m.get("name") == name), None)


def _safe_hit(c: Combatant, foe: Combatant, chart: dict, moves_tbl: dict) -> bool:
    """``c`` has a damaging move (power > 1) whose MIN-roll damage is > 0 and < foe.hp: it can poke, not wipe."""
    for name in c.moves:
        mv = _move_row(name, moves_tbl)
        if not mv or int(mv.get("power", 0)) <= 1:
            continue
        eff = type_mult(chart, mv["type"], list(foe.types))
        if eff <= 0:
            continue
        phys = mv["type"] in PHYSICAL
        d = expected_damage(c.level, mv["power"], c.stats[0] if phys else c.stats[3],
                            foe.stats[1] if phys else foe.stats[3], stab=mv["type"] in c.types, eff=eff) * MIN_ROLL
        if 0 < d < foe.hp:
            return True
    return False


def qualifies_catcher(c: Combatant, lead_level: int, wild, kb=None) -> bool:
    """``c`` fills the catcher role: at least CATCHER_BAND below the lead AND able to damage some wild species
    of the planned map (``wild`` = [(level, species)]) without KOing it at the min roll. A Splash-only Magikarp
    or a status-only move set does not count (the catch METHODS are a later directive; this only scores the role)."""
    moves_tbl = table(kb, "moves")
    if c.level > lead_level - CATCHER_BAND or not wild or not moves_tbl:
        return False
    chart = {(a, d): e for a, d, e in table(kb, "type_chart")}
    return any((foe := trainer_mon(sp, lv, kb)) is not None and _safe_hit(c, foe, chart, moves_tbl) for lv, sp in wild)


def catcher_value(party: list, lead_level: int, wild=None, kb=None) -> float:
    """CATCHER_VALUE when NO member of the party fills the catcher role (the overpower gate: nobody weak enough
    to fight a wild mon without wiping it), else 0. No wild data -> 0 (a safe hit cannot be proven)."""
    if not wild:
        return 0.0
    return 0.0 if any(qualifies_catcher(c, lead_level, wild, kb) for c in (party or ())) else CATCHER_VALUE


def _wild_of(kb, map_id: int) -> list[tuple[int, str]]:
    """[(lowest slot level, species)] of a map's grass table (water slots are not candidates: no Surf yet)."""
    row = table(kb, "wild_by_map").get(map_id) or table(kb, "wild_by_map").get(str(map_id)) or {}
    lo: dict[str, int] = {}
    for lv, sp in row.get("grass") or []:
        lo[sp] = min(lv, lo.get(sp, lv))
    return [(lv, sp) for sp, lv in lo.items()]


def _sim_mon(candidate: Candidate, level: int, kb) -> Combatant | None:
    """The candidate as it fights at ``level`` (its evolved form when EVOLUTIONS says so)."""
    return trainer_mon(form_at(candidate.species, level), level, kb)


def _hurt_margin(party: list, theirs: list, chart: dict, moves: dict, kb) -> float:
    """The hurt-lead fight team_readiness scores: lead at LEAD_HURT, the others as they fight today
    (an evolved MAGIKARP as its GYARADOS)."""
    from pokeagent.magikarp import EVOLVE_LEVEL  # deferred: keep this pure module free of the emulator import
    lead_i = next((i for i, c in enumerate(party) if c.name != "MAGIKARP"), None)
    if lead_i is None:
        return 0.0
    hurt = replace(party[lead_i], hp=int(party[lead_i].hp * LEAD_HURT))
    others = [(trainer_mon("GYARADOS", c.level, kb) or c) if c.name == "MAGIKARP" and c.level >= EVOLVE_LEVEL else c
              for i, c in enumerate(party) if i != lead_i]
    return fight([hurt] + others, theirs, chart, moves)


def _contrib_level(candidate: Candidate, party: list, boss: list, label: str, base_ready: bool, base_margin: float,
                   theirs: list, chart: dict, moves: dict, kb) -> int | None:
    """The lowest level from the caught level to MAX_LEVEL at which the member contributes to ``boss``:
    the hurt-lead team verdict flips to ready, or the hurt-lead margin improves by >= CONTRIB_MARGIN."""
    def contributes_at(level: int) -> bool:
        mon = _sim_mon(candidate, level, kb)
        if mon is None:
            return False
        plus = [*party, mon]
        if not base_ready:
            t = team_readiness(plus, boss, label, kb)
            if t is not None and t.ready:
                return True
        return _hurt_margin(plus, theirs, chart, moves, kb) - base_margin >= CONTRIB_MARGIN

    lo = candidate.level
    if contributes_at(lo):
        return lo
    if not contributes_at(MAX_LEVEL):
        return None
    return next((L for L in range(lo + 1, MAX_LEVEL) if contributes_at(L)), None)


def member_value(candidate: Candidate, party: list, bosses, xp_per_fight: float | None = None,
                 owned_species=(), owned_count: int = 0, kb=None) -> MemberValue:
    """Score one candidate against the next bosses (``bosses`` = [(label, [(level, species)])], already capped
    at BOSS_HORIZON by the caller). Never raises on empty inputs: a zero-value MemberValue comes back."""
    dex = pokedex_value(candidate.species, owned_count, frozenset(owned_species))
    lead_level = party[0].level if party else 0
    cand = candidate
    cv = 0.0
    if candidate.source.startswith("wild:"):
        wild = _wild_of(kb, int(candidate.source.split(":", 1)[1]))
        if wild and candidate.level <= lead_level - CATCHER_BAND and (mon := _sim_mon(candidate, candidate.level, kb)):
            cv = catcher_value(party, lead_level, wild, kb) if qualifies_catcher(mon, lead_level, wild, kb) else 0.0
            if cv:
                cand = replace(candidate, source="catcher")
    contributes: list[str] = []
    lowest: int | None = None
    if party:
        for label, boss in (bosses or ()):
            theirs = [m for lv, n in boss if (m := trainer_mon(n, lv, kb))]
            base = team_readiness(party, boss, label, kb)
            if not theirs or base is None:
                continue
            base_margin = _hurt_margin(party, theirs, {(a, d): e for a, d, e in table(kb, "type_chart")},
                                       table(kb, "moves"), kb)
            hit = _contrib_level(cand, party, boss, label, base.ready, base_margin, theirs,
                                 {(a, d): e for a, d, e in table(kb, "type_chart")}, table(kb, "moves"), kb)
            if hit is not None:
                contributes.append(label)
                lowest = hit if lowest is None else min(lowest, hit)
    fights = fights_to_reach(cand.species, cand.level, lowest, xp_per_fight, kb,
                             trainee=cand.source == "magikarp")
    cost = fights * COST_PER_FIGHT
    gain = float(len(contributes))
    value = gain + dex + cv - cost
    return MemberValue(cand, lowest, tuple(contributes), gain, fights, cost, round(dex, 4), cv, round(value, 4))


def candidates_for(party: list, wild_by_map: dict, maps, magikarp_level: int | None, kb=None) -> list[Candidate]:
    """Every catchable option scored by member_value: (a) each wild grass species on the maps in ``maps`` at the
    lowest level its table gives (``wild:<map id>``; water slots are out - no Surf yet; species with no
    species_by_dex row are skipped silently); (b) the evolution line of each current member (``party-evolution``);
    (c) ONE Magikarp (``magikarp``), judged as the GYARADOS it becomes at 20, at the owned one's level or
    MAGIKARP_START_LEVEL. In-game trades: out of scope, no table."""
    out: list[Candidate] = []
    for m in maps or ():
        row = (wild_by_map or {}).get(m) or (wild_by_map or {}).get(str(m)) or {}
        grass = row.get("grass") or []
        for sp in dict.fromkeys(n for _, n in grass):
            if species_row(sp, kb) is None:
                continue
            out.append(Candidate(sp, min(lv for lv, n in grass if n == sp), f"wild:{int(m)}"))
    for c in party or ():
        if c.name in EVOLUTIONS and c.name != "MAGIKARP":  # an owned Magikarp is the one "magikarp" candidate below
            out.append(Candidate(c.name, c.level, "party-evolution"))
    owned = next((c.level for c in party or () if c.name == "MAGIKARP"), None)
    out.append(Candidate("MAGIKARP", owned or magikarp_level or MAGIKARP_START_LEVEL, "magikarp"))
    return out
