"""game_key in state sidecars: write_state records it, read_meta tolerates its absence, the guard enforces it."""
import json
from pathlib import Path

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.game.spec import LEGACY_FAMILY, GameSpec
from pokeagent.game.state_guard import StateGameMismatch
from pokeagent.statemeta import read_meta, sidecar, write_state


def _spec(key, family, owns) -> GameSpec:
    return GameSpec(
        key=key, title=key, rom_sha1=("A" * 40,), default_rom=Path("roms/x.gb"),
        screen=(2, 2), buttons=("a",), memory_family=family, owns_legacy_paths=owns,
    )


SIBLING = _spec("test-sibling", LEGACY_FAMILY, False)  # Red's family, not the legacy owner


def test_write_state_records_the_game_key(tmp_path):
    emu = FakeEmulator({0xD35E: 1, 0xD362: 18, 0xD361: 10, 0xD163: 1})
    meta = write_state(emu, tmp_path / "s.state")
    assert meta.game_key == "pokemon-red"
    assert json.loads(sidecar(tmp_path / "s.state").read_text())["game_key"] == "pokemon-red"
    assert read_meta(tmp_path / "s.state").game_key == "pokemon-red"


def test_old_sidecar_without_game_key_reads_as_none(tmp_path):
    st = tmp_path / "old.state"
    st.write_bytes(b"opaque")
    sidecar(st).write_text(json.dumps({
        "path": str(st), "digest": "x", "created_at": 0.0, "game": {},
    }), encoding="utf-8")
    meta = read_meta(st)
    assert meta is not None and meta.game_key is None


def test_emulator_without_a_game_attribute_writes_pokemon_red(tmp_path):
    """The phase-3 emulators always carry .game; the fallback covers bare test doubles."""
    class BareEmu:
        def read(self, addr): return 0
        def read_range(self, start, length): return bytes(length)
        def save_state(self, path): Path(path).write_bytes(b"x")

    meta = write_state(BareEmu(), tmp_path / "bare.state")
    assert meta.game_key == "pokemon-red"


def test_red_fake_emulator_round_trips_save_then_load(tmp_path):
    src = FakeEmulator({0xD35E: 1, 0xD362: 18, 0xD361: 10, 0xD163: 1, 0x1234: 0xAB})
    st = tmp_path / "s.state"
    write_state(src, st)
    dst = FakeEmulator()
    dst.load_state(st)
    assert dst.memory[0x1234] == 0xAB


def test_labeled_state_for_another_game_is_refused_before_the_emulator_is_touched(tmp_path):
    src = FakeEmulator({0xD163: 1})
    st = tmp_path / "red.state"
    write_state(src, st)  # sidecar carries game_key "pokemon-red"
    sib = FakeEmulator({0xBEEF: 0x11}, game=SIBLING)
    before = dict(sib.memory)
    with pytest.raises(StateGameMismatch) as e:
        sib.load_state(st)
    assert "pokemon-red" in str(e.value) and "test-sibling" in str(e.value)
    assert sib.memory == before  # refused BEFORE load_state touched the emulator


def test_unlabeled_state_is_refused_for_a_nonlegacy_fake(tmp_path):
    st = tmp_path / "unlabeled.state"
    FakeEmulator({0x1: 0x2}).save_state(st)  # save_state writes no sidecar
    sib = FakeEmulator({0xBEEF: 0x11}, game=SIBLING)
    with pytest.raises(StateGameMismatch):
        sib.load_state(st)
    assert sib.memory == {0xBEEF: 0x11}
