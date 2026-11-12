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
