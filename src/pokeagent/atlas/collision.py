"""collision: the ROM's per-tileset list of walkable tile ids (for explorer.memory, which may not import the atlas).

Each tileset header (0xC7BE, 12 bytes) holds a collision pointer at +5/+6 into the HOME bank (read directly, not bank-relative):
a run of walkable tile ids ended by 0xFF. ROM-checked on Mt Moon's cavern tileset (17): 05 15 18 1A 20 21 22 2A 2D 30, which
matches every tile the agent ever learned as walkable there.
"""
from __future__ import annotations

from pokeagent.atlas import rom_maps

TILESET_TABLE, ENTRY, NUM_TILESETS = 0xC7BE, 12, 24


def walkable_ids(rom: bytes, tileset: int) -> frozenset:
    """The walkable tile ids of ``tileset`` read from the ROM bytes (empty for an unknown tileset)."""
    ids: set[int] = set()
    if 0 <= tileset < NUM_TILESETS:
        o = rom[TILESET_TABLE + ENTRY * tileset + 5] | rom[TILESET_TABLE + ENTRY * tileset + 6] << 8
        while o < len(rom) and rom[o] != 0xFF and len(ids) < 256:
            ids.add(rom[o]); o += 1
    return frozenset(ids)


def rom_walkable_ids(rom_path: str = "roms/Pokemon Red.gb"):
    """``tileset -> frozenset of walkable tile ids`` (empty set for an unknown tileset); None when the ROM is unreadable."""
    try:
        rom = rom_maps.load(rom_path)
    except OSError:
        return None
    cache: dict[int, frozenset] = {}

    def walkable(tileset: int) -> frozenset:
        if tileset not in cache:
            cache[tileset] = walkable_ids(rom, tileset)
        return cache[tileset]
    return walkable
