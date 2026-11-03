import dataclasses
import json

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.ram import RAM_MAP, GameState, decode_bcd, read_state


def test_decode_bcd_basic():
    assert decode_bcd(b"\x01\x23\x45") == 12345


def test_decode_bcd_zeroes():
    assert decode_bcd(b"\x00\x00\x00") == 0


def test_decode_bcd_nines():
    assert decode_bcd(b"\x99\x99\x99") == 999999


def test_read_state_on_scripted_fake():
    emu = FakeEmulator()
    emu.set(RAM_MAP["map_id"], 0x26)
    emu.set(RAM_MAP["player_x"], 3)
    emu.set(RAM_MAP["player_y"], 6)
    emu.set(RAM_MAP["party_count"], 1)
    emu.set(RAM_MAP["badges"], 0b00000101)
    emu.set(RAM_MAP["in_battle"], 1)
    emu.set(RAM_MAP["money"], 0x00)
    emu.set(RAM_MAP["money"] + 1, 0x30)
    emu.set(RAM_MAP["money"] + 2, 0x00)
    state = read_state(emu)
    assert state == GameState(
        map_id=0x26, x=3, y=6, party_count=1,
        badges=0b00000101, badge_count=2, in_battle=True, money=3000,
    )


def test_read_state_defaults_zeroes_not_in_battle():
    state = read_state(FakeEmulator())
    assert state.map_id == 0
    assert state.in_battle is False
    assert state.badge_count == 0
    assert state.money == 0


def test_as_dict_is_plain_json_serializable_dict():
    state = GameState(map_id=0x26, x=3, y=6, party_count=1, badges=5,
                      badge_count=2, in_battle=False, money=3000)
    d = state.as_dict()
    assert d["map_id"] == 0x26
    assert d["badge_count"] == 2
    json.dumps(d)


def test_summary_format():
    state = GameState(map_id=0x26, x=3, y=6, party_count=1, badges=0,
                      badge_count=0, in_battle=False, money=3000)
    assert state.summary() == "map=0x26 pos=(3,6) party=1 badges=0 battle=no money=3000"


def test_summary_battle_yes():
    state = GameState(map_id=1, x=0, y=0, party_count=0, badges=3,
                      badge_count=2, in_battle=True, money=0)
    assert "battle=yes" in state.summary()
    assert "badges=2" in state.summary()


def test_gamestate_is_frozen():
    state = read_state(FakeEmulator())
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.money = 1
