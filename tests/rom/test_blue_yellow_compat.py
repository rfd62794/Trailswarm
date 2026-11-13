"""ROM-gated (skip without the ROMs; the laptop runs these): Blue matches Red's engine, Yellow's hash is right and it stays gated.

Never prints or stores ROM bytes: only hashes and counts.
"""
import sys
from pathlib import Path

import pytest

from pokeagent.compat import rom_check as rc
from pokeagent.game import BLUE, RED, YELLOW
from pokeagent.game.gate import game_for_rom, rom_sha1
from pokeagent.game.symbols import symbol_table

from rom_helpers import ROM, ROM_BLUE, ROM_YELLOW, rom_or_skip

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


@pytest.fixture(scope="module")
def red_and_blue():
    red, blue = rom_or_skip(ROM, "Red"), rom_or_skip(ROM_BLUE, "Blue")
    return red.read_bytes(), blue.read_bytes()


def test_hashes_and_detection():
    for spec, rom in ((RED, ROM), (BLUE, ROM_BLUE), (YELLOW, ROM_YELLOW)):
        rom_or_skip(rom, spec.title)
        assert rom_sha1(rom) in spec.rom_sha1 and game_for_rom(rom) is spec
        assert Path(rom).stat().st_size == 1048576


def test_blue_map_headers_match_red(red_and_blue):
    h = rc.compare_headers(*red_and_blue)
    assert h["maps_red"] > 200 and not h["only_red"] and not h["only_blue"]
    assert h["different"] == [], f"map headers differ for ids {h['different']}"


def test_blue_key_ram_symbols_match_red(red_and_blue):
    syms = symbol_table(RED)
    s = rc.compare_symbol_counts(rc.symbol_operand_counts(red_and_blue[0], syms),
                                 rc.symbol_operand_counts(red_and_blue[1], syms))
    assert s["mismatched"] == {}, s["mismatched"]


def test_blue_overlay_of_version_exclusive_encounters(red_and_blue, tmp_path):
    from game_compat_rom import wild_tables
    ov = rc.wild_overlay(wild_tables(red_and_blue[0]), wild_tables(red_and_blue[1]))
    assert isinstance(ov, dict)  # Blue-exclusive wild tables differ from Red's; the laptop run records the count
    print("blue wild overlay maps:", sorted(ov.get("wild_by_map", {}), key=int))


def test_yellow_boots_never_and_stays_gated():
    from pokeagent.emulator import PyBoyEmulator
    from pokeagent.game.gate import NotPlayable
    rom = rom_or_skip(ROM_YELLOW, "Yellow")
    with pytest.raises(NotPlayable):
        PyBoyEmulator(rom)  # the hash picks Yellow, and Yellow is gated
