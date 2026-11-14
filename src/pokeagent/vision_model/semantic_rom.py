"""Build the per-tileset semantic tables from ROM bytes (a ``bytes`` argument, never a path).

Header entry i sits at ``TILESET_TABLE + ENTRY*i``: +5/+6 the collision-list pointer
(the walkable tile ids), +7/+8/+9 the three counter tile ids (0xFF unused), +10 the
tall-grass tile id (0xFF none). A tileset whose header runs past the end of the
buffer is skipped, never an exception for the whole call.
"""
from __future__ import annotations

from pokeagent.atlas.collision import ENTRY, NUM_TILESETS, TILESET_TABLE, walkable_ids
from pokeagent.atlas.tiles import load_tileset
from pokeagent.vision_model.semantic import TilesetFacts, tile_table


def facts_from_rom(rom: bytes, tileset: int) -> TilesetFacts:
    """The TilesetFacts of one tileset read out of the ROM bytes."""
    e = TILESET_TABLE + ENTRY * tileset
    return TilesetFacts(
        tileset=tileset,
        walkable=walkable_ids(rom, tileset),
        grass=rom[e + 10],
        counters=frozenset(b for b in rom[e + 7:e + 10] if b != 0xFF))


def tables_from_rom(rom: bytes, tilesets=range(NUM_TILESETS)) -> tuple[dict[int, dict[int, str]], dict[int, int]]:
    """(tileset -> tile id -> class, tileset -> ambiguous id count).

    A tileset whose header or blockset cannot be read off the buffer is absent
    from the result, so its tile rows fall back to ``other`` instead of failing.
    """
    tables, ambiguous = {}, {}
    for ts in tilesets:
        if not 0 <= ts < NUM_TILESETS:
            continue
        try:
            facts = facts_from_rom(rom, ts)
            blockset = load_tileset(rom, ts).blockset
        except IndexError:
            continue
        table, amb = tile_table(blockset, facts)
        tables[ts], ambiguous[ts] = table, amb
    return tables, ambiguous
