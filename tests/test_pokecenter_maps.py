"""POKECENTER_MAPS comes from the ROM map names, not a hand-typed list."""
import json

from pokeagent.explorer.world import POKECENTER_MAPS, pokecenter_maps


def test_all_eleven_pokecenters_including_the_original_four():
    assert len(POKECENTER_MAPS) == 11
    assert {41, 58, 0x44, 0x40} <= set(POKECENTER_MAPS)
    assert {0x51, 0x59, 0x85, 0x8D, 0x9A, 0xAB, 0xB6} <= set(POKECENTER_MAPS)  # Rock Tunnel .. Saffron
    assert list(POKECENTER_MAPS) == sorted(POKECENTER_MAPS)


def test_other_center_named_maps_are_not_pokecenters():
    assert not ({220, 221, 239} & set(POKECENTER_MAPS))  # Safari Zone centre, its rest house, the Trade Center


def test_derivation_from_a_names_file_and_the_fallback(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps({"1": "FOO_POKECENTER", "2": "BAR_CENTER", "3": "BAZ_POKECENTER"}))
    assert pokecenter_maps(p) == (1, 3)
    assert pokecenter_maps(tmp_path / "missing.json") == (41, 58, 0x44, 0x40)
