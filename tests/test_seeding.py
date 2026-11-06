"""--seed must change the game (the RNG), and seed 0 must stay exactly as before."""
from pathlib import Path

import pytest

from pokeagent.emulator import Button, PyBoyEmulator
from pokeagent.explorer.seeding import IDLE_RANGE, idle_frames

ROOT = Path(__file__).resolve().parents[1]


def test_seed_zero_and_none_do_not_idle():
    assert idle_frames(None) == 0 and idle_frames(0) == 0


def test_idle_frames_in_range_and_varied():
    vals = [idle_frames(s) for s in range(1, 41)]
    assert all(0 <= v < IDLE_RANGE for v in vals)
    assert len(set(vals)) >= 30 and idle_frames(7) == idle_frames(7)


def _first_encounter(seed):
    rom, st = ROOT / "roms" / "Pokemon Red.gb", ROOT / "runs" / "checkpoints" / "to_route1.state"
    if not (rom.exists() and st.exists()):
        pytest.skip("ROM or to_route1 checkpoint not present")
    emu = PyBoyEmulator(rom, headless=True)
    try:
        emu.load_state(st)
        emu.tick(30)
        emu.tick(idle_frames(seed))
        cycle = [Button.UP] * 6 + [Button.DOWN] * 6
        for n in range(1, 400):  # pace in Route 1's grass until the first wild battle
            emu.press(cycle[n % 12], 8, 8)
            if emu.read(0xD057):
                emu.tick(120)
                return n, emu.read(0xCFE5), emu.read(0xCFF3)
        return None
    finally:
        emu.close()


def test_different_seeds_give_different_first_encounters():
    results = {s: _first_encounter(s) for s in (0, 7, 11, 23)}
    assert all(results.values())
    assert len(set(results.values())) >= 3, results  # steps-to-encounter / species / level differ
    assert _first_encounter(0) == results[0]  # seed 0 is reproducible
