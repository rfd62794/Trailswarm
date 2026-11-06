"""battle_run: in a dungeon, a wild Pokemon we already own is not worth a fight - run, and keep walking to the exit."""
from __future__ import annotations

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.world import DUNGEON_MAPS

POKEDEX_OWNED = 0xD2F7  # wPokedexOwned: bit (dex - 1) of the byte (dex - 1) // 8


def owned(emu, species: int) -> bool:
    """Is this internal species id already in the Pokedex as owned? False when unknown (so we do not skip a new one)."""
    dex = int(((ROM_KB or {}).get("dex_of_internal") or {}).get(str(species), 0) or 0)
    return dex > 0 and bool(emu.read(POKEDEX_OWNED + (dex - 1) // 8) >> ((dex - 1) % 8) & 1)


def cave_run(ctx: ExplorerContext, kind: int, species: int) -> bool:
    """Wild fight (kind 1) inside DUNGEON_MAPS against a species already owned."""
    return kind == 1 and ctx.view.m in DUNGEON_MAPS and species > 0 and owned(ctx.emu, species)
