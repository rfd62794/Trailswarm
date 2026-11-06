"""Party panel rows for the viewer: species, level, HP, DVs and stat exp per party mon, from RAM."""
from __future__ import annotations

from pokeagent.emulator import Emulator
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.stats import dv_text, stat_exp_text
from pokeagent.ramstructs import read_party
from pokeagent.snapshot import PartyMon


def party_rows(emu: Emulator) -> list[PartyMon]:
    """One snapshot PartyMon per occupied party slot (empty list when RAM is not a live game)."""
    names = (ROM_KB or {}).get("name_of_internal", {})
    return [PartyMon(species=names.get(str(m.species), f"#{m.species}"), level=m.level, hp=m.hp, max_hp=m.max_hp,
                     dvs=dv_text(m), stat_exp=stat_exp_text(m)) for m in read_party(emu)]
