import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.ramstructs import (decode_battle_mon, decode_item_list, decode_party_mon, read_bag, read_enemy_mon,
                                  read_party)
from pokeagent.ramworld import (bit_indices, decode_map_header, event_flag, read_badges, read_money,
                                read_play_time, read_pokedex)

# A level-5 Bulbasaur as captured at first_pokemon (after the give): DVs 0x5C57, stat exp 0.
BULBA = bytes([153, 0, 20, 0, 0, 22, 3, 45, 33, 45, 0, 0, 218, 55, 0, 0, 135, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               92, 87, 35, 40, 0, 0, 5, 0, 20, 0, 10, 0, 11, 0, 10, 0, 12])


def test_decode_party_mon_fields():
    m = decode_party_mon(BULBA)
    assert (m.species, m.hp, m.level, m.max_hp) == (153, 20, 5, 20)
    assert m.moves == (33, 45, 0, 0) and m.pp == (35, 40, 0, 0)
    assert m.ot_id == 0xDA37 and m.exp == 135
    assert m.dv_word == 0x5C57 and m.stats == (10, 11, 10, 12) and m.stat_exp == (0,) * 5


def test_decode_party_mon_multibyte_big_endian():
    raw = bytearray(BULBA)
    raw[17:19] = (0x03, 0xE8)       # HP stat exp 1000
    raw[34:36] = (0x01, 0x2C)       # max HP 300
    raw[14:17] = (0x01, 0x02, 0x03)
    m = decode_party_mon(bytes(raw))
    assert m.stat_exp[0] == 1000 and m.max_hp == 300 and m.exp == 0x010203


def test_decode_party_mon_short_raises():
    with pytest.raises(ValueError):
        decode_party_mon(b"\x00" * 10)


def test_decode_battle_mon_and_mods():
    raw = bytearray(29)
    raw[0], raw[1:3], raw[14], raw[15:17] = 36, (0, 30), 8, (0, 31)
    raw[12:14] = (0xAB, 0xCD)
    raw[17:25] = bytes([0, 12, 0, 11, 0, 13, 0, 9])
    raw[25:29] = bytes([35, 25, 0, 0])
    b = decode_battle_mon(bytes(raw), bytes([7, 5, 9, 7, 7, 7]))
    assert (b.species, b.hp, b.level, b.max_hp) == (36, 30, 8, 31)
    assert b.dv_word == 0xABCD and b.stats == (12, 11, 13, 9) and b.pp == (35, 25, 0, 0)
    assert b.mod_stages() == (0, -2, 2, 0, 0, 0)


def test_item_list_and_reads():
    assert decode_item_list(bytes([2, 4, 5, 20, 1, 0xFF, 0, 0]), 20) == [(4, 5), (20, 1)]
    assert decode_item_list(bytes([200]) + bytes(60), 20)[:1] == [(0, 0)] and len(decode_item_list(bytes([200]) + bytes(60), 20)) == 20
    emu = FakeEmulator({0xD31D: 1, 0xD31E: 20, 0xD31F: 3, 0xD320: 0xFF})
    assert read_bag(emu) == [(20, 3)]


def test_read_party_uses_count_and_slots():
    mem = {0xD163: 2}
    for i, b in enumerate(BULBA):
        mem[0xD16B + i] = b
        mem[0xD197 + i] = b
    emu = FakeEmulator(mem)
    party = read_party(emu)
    assert len(party) == 2 and party[1].species == 153 and party[1].level == 5
    assert read_party(FakeEmulator({})) == []
    assert read_enemy_mon(FakeEmulator({0xCFE5: 9})).species == 9


def test_world_readers():
    emu = FakeEmulator({0xD347: 0x01, 0xD348: 0x23, 0xD349: 0x45, 0xD356: 0b101, 0xD2F7: 0b11, 0xD30A: 0b111,
                        0xDA41: 1, 0xDA43: 7, 0xDA44: 9})
    assert read_money(emu) == 12345
    assert read_badges(emu) == ["boulder", "thunder"]
    assert read_pokedex(emu) == ([1, 2], [1, 2, 3])
    assert str(read_play_time(emu)) == "1:07:09"
    assert bit_indices(bytes([0b10000001, 1])) == [0, 7, 8]
    flags = bytes([0, 0b100])
    assert event_flag(flags, 10) and not event_flag(flags, 9)


def test_decode_map_header():
    warps = bytes([11, 4, 2, 255, 11, 5, 2, 255]) + bytes(120)
    h = decode_map_header(bytes([0, 9, 10]), warps, 2, bytes([27, 9]) + bytes(30), 1, bytes([255, 1]) + bytes(30), 1)
    assert (h.width, h.height, h.tiles) == (10, 9, (20, 18))
    assert len(h.warps) == 2 and h.warps[0].dest_map == 255 and h.signs == ((27, 9),) and h.sprites == ((255, 1),)
