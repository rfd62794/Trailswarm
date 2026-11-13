"""Shared constants and the state loader for the ROM-backed party tests.

The ROM is gitignored and never present in a Devin worktree; the states are
committed fixtures. Missing pieces must skip, never fail.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / "roms" / "Pokemon Red.gb"
STATES = ROOT / "tests" / "fixtures" / "rom_states"


def load(emu, name):          # returns the emulator with the state loaded and one frame ticked
    path = STATES / f"{name}.state"
    if not path.exists():
        pytest.skip(f"needs tests/fixtures/rom_states/{name}.state (controller copies it in)")
    emu.load_state(path)
    emu.tick(1)
    return emu


def _game_rom(key):
    """The game's ROM by its spec path (hash-checked at use, not here); None when absent."""
    from pokeagent.game import GAMES
    from pokeagent.game.gate import find_rom
    return find_rom(GAMES[key], ROOT)


ROM_BLUE = _game_rom("pokemon-blue")      # roms/Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb
ROM_YELLOW = _game_rom("pokemon-yellow")  # roms/Pokemon - Yellow Version - Special Pikachu Edition (...).gb


def rom_or_skip(path, what):
    if path is None or not Path(path).exists():
        pytest.skip(f"needs the {what} ROM under roms/ (gitignored; the laptop runs these)")
    return Path(path)
