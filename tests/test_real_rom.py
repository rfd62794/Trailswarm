import os
from pathlib import Path

import pytest

from pokeagent.emulator import PyBoyEmulator
from pokeagent.ram import read_state


@pytest.mark.skipif(
    not os.environ.get("POKEAGENT_ROM") or not Path(os.environ["POKEAGENT_ROM"]).exists(),
    reason="no ROM",
)
def test_real_rom_boots_ticks_and_reads_state():
    emu = PyBoyEmulator(Path(os.environ["POKEAGENT_ROM"]), headless=True)
    try:
        emu.tick(60)
        state = read_state(emu)
        assert state.map_id >= 0
        assert emu.screenshot().size == (160, 144)
    finally:
        emu.close()
