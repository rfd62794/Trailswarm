"""A combatant for matchup maths: our party read from RAM, or a trainer's party built from ROM base stats."""
from __future__ import annotations

from dataclasses import dataclass, replace

from pokeagent.knowledge.kb import table

STAT4 = ("atk", "def", "spd", "spc")
TRAINER_DV = 8             # Gen 1 trainer mons carry middling DVs (0x98 0x88); no stat exp


@dataclass(frozen=True)
class Combatant:
    name: str
    level: int
    types: tuple[str, ...]
    hp: int                           # max HP (we assume a full heal before the boss)
    stats: tuple[int, int, int, int]  # atk, def, spd, spc
    moves: tuple[str, ...]
    dv: tuple[int, ...] = ()          # atk def spd spc hp (for re-levelling our own mon)
    sexp: tuple[int, ...] = ()        # hp atk def spd spc


def species_row(name: str, kb: dict | None = None) -> dict | None:
    return next((r for r in table(kb, "species_by_dex").values() if r.get("name") == name), None)


def moves_at(name: str, level: int, kb: dict | None = None, after: int = 0) -> list[str]:
    """The (up to 4) moves a mon of `level` has: level-1 moves, then each level-up move <= level, oldest pushed out.
    With `after`, only the level-up moves learned in (after, level]."""
    row, ls = species_row(name, kb), (table(kb, "learnsets").get(name) or {}).get("learnset", [])
    mv = [] if after else list(row["moves1"] if row else [])
    for lv, m in ls:
        if after < lv <= level and m not in mv:
            mv.append(m)
    return mv[-4:]


def _stats(row: dict, level: int, dv, sexp) -> tuple[int, tuple[int, int, int, int]]:
    from pokeagent.explorer.stats import stat_value
    hp = stat_value(row["hp"], dv[4] if len(dv) > 4 else TRAINER_DV, sexp[0] if sexp else 0, level, hp=True)
    return hp, tuple(stat_value(row[k], dv[i] if dv else TRAINER_DV, sexp[i + 1] if sexp else 0, level)
                     for i, k in enumerate(STAT4))  # type: ignore[return-value]


def _types(row: dict) -> tuple[str, ...]:
    return tuple(dict.fromkeys((row["type1"], row["type2"])))


def trainer_mon(name: str, level: int, kb: dict | None = None) -> Combatant | None:
    row = species_row(name, kb)
    if row is None:
        return None
    hp, st = _stats(row, level, (), ())
    return Combatant(name, level, _types(row), hp, st, tuple(moves_at(name, level, kb)))


def our_party(emu, kb: dict | None = None) -> list[Combatant]:
    """The party from RAM with its real stats and known moves ([] when the ROM tables are missing)."""
    from pokeagent.explorer.stats import dvs, stat_exp
    from pokeagent.ramstructs import read_party
    names, moves = table(kb, "name_of_internal"), table(kb, "moves")
    out = []
    for m in read_party(emu):
        row = species_row(names.get(str(m.species), ""), kb)
        if row is None or not m.level:
            continue
        d, s = dvs(m), stat_exp(m)
        out.append(Combatant(row["name"], m.level, _types(row), m.max_hp, tuple(m.stats),
                             tuple(moves[str(i)]["name"] for i in m.moves if str(i) in moves),
                             (d["attack"], d["defense"], d["speed"], d["special"], d["hp"]),
                             (s["hp"], s["attack"], s["defense"], s["speed"], s["special"])))
    return out


def at_level(c: Combatant, level: int, kb: dict | None = None) -> Combatant:
    """The same mon at another level (stats from its DVs / stat exp; moves it would learn on the way are added)."""
    row = species_row(c.name, kb)
    if row is None or level == c.level:
        return c
    hp, st = _stats(row, level, c.dv, c.sexp)
    extra = moves_at(c.name, level, kb, after=c.level) if level > c.level else []
    return replace(c, level=level, hp=hp, stats=st, moves=tuple(dict.fromkeys((*c.moves, *extra))))
