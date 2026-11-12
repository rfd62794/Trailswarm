"""stable-retro type strings and data.json dicts from a measured address table (synthetic, no ROM)."""
from __future__ import annotations

import pytest

from pokeagent.ram_lookup import MapEntry
from pokeagent.ramlab.address_table import build_table
from pokeagent.ramlab.observations import Sample
from pokeagent.ramlab.retro_vars import build_retro_data, retro_type, untyped_count


@pytest.mark.parametrize("enc, size, want", [
    ("u8", 1, "|u1"), ("bitmask", 1, "|u1"), ("u16be", 2, ">u2"), ("bcd", 3, ">d3"),
    ("bcd", 1, ">d1"), ("bcd", 4, ">d4"), ("bcd", 5, None),
    ("bytes", 44, None), ("text", 11, None), ("bitmask", 19, None), ("u8", 256, None),
])
def test_retro_type_table(enc, size, want):
    assert retro_type(MapEntry("wX", 0xD000, size, "misc", enc)) == want


def measured(addr):
    return [Sample(addr, 1, "a"), Sample(addr, 2, "b")]


def table():
    entries = [MapEntry("wCurMap", 0xD35E, 1, "map", "u8", True),
               MapEntry("wPlayerMoney", 0xD347, 3, "items", "bcd", True),
               MapEntry("wPartyMon1", 0xD16B, 44, "party"),
               MapEntry("wJoyIgnore", 0xCD6B, 1, "misc", "bitmask")]
    red = measured(0xD35E) + measured(0xD16B) + [Sample(0xD347, 9, "a")] + [Sample(0xCD6B, 1, "a"), Sample(0xCD6B, 2, "a")]
    return build_table(entries, {"pokemon-red": red})


def test_data_json_has_only_measured_typed_entries_by_default():
    t = table()
    assert build_retro_data(t, "pokemon-red") == {"info": {"wCurMap": {"address": 0xD35E, "type": "|u1"}}}
    assert untyped_count(t, "pokemon-red") == 1


def test_include_believed_adds_believed():
    data = build_retro_data(table(), "pokemon-red", include=("measured", "believed"))
    assert data == {"info": {"wCurMap": {"address": 0xD35E, "type": "|u1"},
                             "wPlayerMoney": {"address": 0xD347, "type": ">d3"},
                             "wJoyIgnore": {"address": 0xCD6B, "type": "|u1"}}}


def test_data_json_shape_and_decimal_address():
    t = build_table([MapEntry("wCurMap", 0xD35E, 1, "map", "u8", True)], {"pokemon-red": measured(0xD35E)})
    assert build_retro_data(t, "pokemon-red") == {"info": {"wCurMap": {"address": 54110, "type": "|u1"}}}


def test_empty_gives_empty_info():
    assert build_retro_data(table(), "pokemon-blue") == {"info": {}}
    assert build_retro_data(build_table([], {}), "pokemon-red") == {"info": {}}
