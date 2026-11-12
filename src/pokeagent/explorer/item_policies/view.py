"""The party as plain data for the item policies, and which slot does the fighting."""
from __future__ import annotations

from dataclasses import dataclass

MAGIKARP = "MAGIKARP"


@dataclass(frozen=True)
class Mon:
    slot: int
    species: str
    level: int
    moves: tuple[str, ...]
    hp: int
    max_hp: int
    stat_exp: tuple[int, ...] = (0, 0, 0, 0, 0)  # hp atk def spd spc


def read_mons(emu, kb: dict | None = None) -> list[Mon]:
    """The party from RAM; species or moves the ROM tables do not know read as '#id'."""
    from pokeagent.knowledge.kb import table
    from pokeagent.ramstructs import read_party
    names, moves = table(kb, "name_of_internal"), table(kb, "moves")
    return [Mon(i, names.get(str(m.species), f"#{m.species}"), m.level,
                tuple(moves.get(str(mv), {}).get("name", f"#{mv}") for mv in m.moves if mv), m.hp, m.max_hp, tuple(m.stat_exp))
            for i, m in enumerate(read_party(emu))]


def fighter_slot_of(party: list[Mon]) -> int | None:
    """Party slot that does the fighting: the first living member without a Magikarp (slot 0 when all are down), else the
    strongest non-Magikarp (None: only Magikarps). Same rule as cave_topup.fighter_slot / magikarp.fighter, on plain data."""
    if not party:
        return None
    real = [m for m in party if m.species != MAGIKARP]
    if len(real) == len(party):
        return next((m for m in party if m.hp > 0), party[0]).slot
    return max(real, key=lambda m: (m.hp > 0, m.level, m.hp)).slot if real else None
