"""semantic_rom.py: facts and tile tables off a synthetic ROM bytearray (no files)."""
from __future__ import annotations

from pokeagent.atlas.collision import ENTRY, TILESET_TABLE
from pokeagent.vision_model.semantic_rom import facts_from_rom, tables_from_rom

TS = 3


def make_rom() -> bytes:
    """Tileset 3: collision list {5,6,7} at 0x1000, counters {0x30}, grass id 0x06,
    and one block at 0x2000 whose cells cover walkable, grass and counter tiles."""
    rom = bytearray(0xD000)
    e = TILESET_TABLE + ENTRY * TS
    rom[e] = 1                                              # bank -> blockset reads at ptr
    rom[e + 1:e + 3] = (0x2000).to_bytes(2, "little")       # blockset pointer
    rom[e + 3:e + 5] = (0x3000).to_bytes(2, "little")       # gfx pointer
    rom[e + 5:e + 7] = (0x1000).to_bytes(2, "little")       # collision-list pointer
    rom[e + 7:e + 10] = bytes([0x30, 0xFF, 0xFF])           # counter tile ids
    rom[e + 10] = 0x06                                      # tall-grass tile id
    rom[0x1000:0x1004] = bytes([0x05, 0x06, 0x07, 0xFF])
    rom[0x2000:0x2010] = bytes([0x10, 0x10, 0x20, 0x20,
                              0x05, 0x10, 0x05, 0x20,
                              0x40, 0x40, 0x30, 0x30,
                              0x06, 0x40, 0x30, 0x30])
    return bytes(rom)


def test_facts_from_rom():
    f = facts_from_rom(make_rom(), TS)
    assert f.tileset == TS
    assert f.walkable == frozenset({5, 6, 7})
    assert f.grass == 0x06
    assert f.counters == frozenset({0x30})


def test_tables_from_rom():
    tables, ambiguous = tables_from_rom(make_rom(), tilesets=(TS,))
    assert tables[TS] == {0: "solid",                          # the zero padding blocks
                          0x05: "walkable", 0x10: "walkable", 0x20: "walkable",
                          0x06: "grass", 0x40: "grass", 0x30: "counter"}
    assert ambiguous[TS] == 0


def test_unreadable_tileset_is_skipped_not_raised():
    short = make_rom()[:TILESET_TABLE + ENTRY * TS + 5]     # ends inside the header
    tables, ambiguous = tables_from_rom(short, tilesets=(TS,))
    assert TS not in tables and TS not in ambiguous
