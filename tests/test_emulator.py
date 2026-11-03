from pathlib import Path

import pytest
from PIL import Image

from pokeagent.emulator import Button, Emulator, FakeEmulator, PyBoyEmulator


def test_fake_records_presses_and_frames():
    emu = FakeEmulator()
    emu.press(Button.A)
    emu.press(Button.DOWN, hold_frames=4, settle_frames=10)
    assert emu.presses == [Button.A, Button.DOWN]
    assert emu.frames == (8 + 16) + (4 + 10)


def test_none_ticks_without_pressing():
    emu = FakeEmulator()
    emu.press(Button.NONE)
    assert emu.presses == []
    assert emu.frames == 8 + 16


def test_tick_counts_frames():
    emu = FakeEmulator()
    emu.tick(60)
    assert emu.frames == 60


def test_read_defaults_to_zero_and_set_scripts_state():
    emu = FakeEmulator()
    assert emu.read(0xD35E) == 0
    emu.set(0xD35E, 0x26)
    assert emu.read(0xD35E) == 0x26


def test_read_range_returns_bytes_and_defaults_zero():
    emu = FakeEmulator({0x10: 0x01, 0x11: 0x23, 0x12: 0x45})
    assert emu.read_range(0x10, 3) == b"\x01\x23\x45"
    assert emu.read_range(0x20, 2) == b"\x00\x00"


def test_screenshot_is_blank_160x144_rgb():
    img = FakeEmulator().screenshot()
    assert isinstance(img, Image.Image)
    assert img.size == (160, 144)
    assert img.mode == "RGB"


def test_save_load_state_round_trip(tmp_path):
    emu = FakeEmulator({0xD35E: 0x26, 0x1234: 7})
    path = tmp_path / "state.json"
    emu.save_state(path)
    fresh = FakeEmulator()
    fresh.load_state(path)
    assert fresh.read(0xD35E) == 0x26
    assert fresh.read(0x1234) == 7
    assert fresh.read(0x9999) == 0


def test_fake_conforms_to_emulator_protocol():
    assert isinstance(FakeEmulator(), Emulator)


def test_pyboy_emulator_missing_rom_raises_file_not_found():
    with pytest.raises(FileNotFoundError) as exc:
        PyBoyEmulator(Path("nope.gb"))
    assert "nope.gb" in str(exc.value)


def test_fake_close_is_idempotent():
    emu = FakeEmulator()
    emu.close()
    emu.close()
    assert emu.closed
