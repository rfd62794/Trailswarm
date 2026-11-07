"""BattleStart must read the enemy species from wEnemyMonSpecies (0xCFE5), not 0xCFD7 (wPlayerMoveMaxPP)."""
from pathlib import Path

import pytest

from pokeagent.adapters.event_feed import EventFeed
from pokeagent.emulator import FakeEmulator

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "roms" / "Pokemon Red.gb"
BASE = ROOT / "baselines"


def _start(emu):
    feed = EventFeed()
    feed._battle_events(emu, None)
    return next(e for e in feed.bus.since(0) if e["type"] == "battle_start")


def test_species_comes_from_enemy_mon_not_move_pp():
    # 0xCFD7 holds a move's max PP (25 here == Gastly's internal id 0x19); 0xCFE5 is the real enemy species.
    emu = FakeEmulator({0xD057: 1, 0xCFD7: 0x19, 0xCFE5: 36, 0xCFF3: 5})
    feed = EventFeed()
    feed._mon = lambda i: {0x19: "GASTLY", 36: "PIDGEY"}.get(i, f"#{i}")
    feed._battle_events(emu, None)
    ev = next(e for e in feed.bus.since(0) if e["type"] == "battle_start")
    assert ev["species"] == "PIDGEY" and ev["enemy_level"] == 5


@pytest.mark.skipif(not ROM.exists() or not (BASE / "battle_matrix_pidgey_5.state").exists(), reason="no ROM / baselines")
@pytest.mark.parametrize("name,want", [("pidgey_5", "PIDGEY"), ("rattata_3", "RATTATA"), ("weedle_5", "WEEDLE"), ("pikachu_12", "PIKACHU")])
def test_battle_baselines(name, want):
    from pokeagent.emulator import PyBoyEmulator
    emu = PyBoyEmulator(ROM)
    try:
        emu.load_state(BASE / f"battle_matrix_{name}.state")
        assert _start(emu)["species"] == want
    finally:
        emu.close()
