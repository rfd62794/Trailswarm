"""collision: the ROM's per-tileset list of walkable tile ids (for explorer.memory, which may not import the atlas).

Each tileset header (0xC7BE, 12 bytes) holds a collision pointer at +5/+6 into the HOME bank (read directly, not bank-relative):
a run of walkable tile ids ended by 0xFF. ROM-checked on Mt Moon's cavern tileset (17): 05 15 18 1A 20 21 22 2A 2D 30, which
matches every tile the agent ever learned as walkable there.
"""
from __future__ import annotations

from pokeagent.atlas import rom_maps
from pokeagent.game.pokemon_red import RED

# str signature default, forward slashes on every OS; RED-pinned: fixed at def time, POKEAGENT_GAME must not change it
_DEFAULT_ROM = str(RED.default_rom).replace("\\", "/")

TILESET_TABLE, ENTRY, NUM_TILESETS = 0xC7BE, 12, 24
PAIRS_LAND = 0xC7E  # TilePairCollisionsLand: (tileset, tileA, tileB) triples ended by 0xFF; ROM-verified 2026-11-06


def tile_pairs(rom: bytes, tileset: int, start: int = PAIRS_LAND) -> frozenset:
    """Tile-id pairs between which walking is blocked on ``tileset`` even though both are walkable (cave elevation steps:
    Mt Moon's floor 0x05 against 0x20/0x41/0x2A/0x21 on the cavern tileset 17). Both orders are included."""
    out, o = set(), start
    while o + 2 < len(rom) and rom[o] != 0xFF and len(out) < 512:
        if rom[o] == tileset:
            out.add((rom[o + 1], rom[o + 2])); out.add((rom[o + 2], rom[o + 1]))
        o += 3
    return frozenset(out)


def rom_tile_pairs(rom_path: str = _DEFAULT_ROM):
    """``tileset -> frozenset of (a, b) pairs`` (both orders); None when the ROM is unreadable."""
    try:
        rom = rom_maps.load(rom_path)
    except OSError:
        return None
    cache: dict[int, frozenset] = {}

    def pairs(tileset: int) -> frozenset:
        if tileset not in cache:
            cache[tileset] = tile_pairs(rom, tileset)
        return cache[tileset]
    return pairs


def walkable_ids(rom: bytes, tileset: int) -> frozenset:
    """The walkable tile ids of ``tileset`` read from the ROM bytes (empty for an unknown tileset)."""
    ids: set[int] = set()
    if 0 <= tileset < NUM_TILESETS:
        o = rom[TILESET_TABLE + ENTRY * tileset + 5] | rom[TILESET_TABLE + ENTRY * tileset + 6] << 8
        while o < len(rom) and rom[o] != 0xFF and len(ids) < 256:
            ids.add(rom[o]); o += 1
    return frozenset(ids)


def rom_walkable_ids(rom_path: str = _DEFAULT_ROM):
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
