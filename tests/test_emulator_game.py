from pathlib import Path

import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.game import GameSpec

TINY = GameSpec(
    key="tiny-game",
    title="Tiny",
    rom_sha1=("B" * 40,),
    default_rom=Path("roms/Tiny.gb"),
    screen=(2, 2),
    buttons=("a", "b", "start"),
)


def test_red_fake_screen_size_and_frames():
    emu = FakeEmulator()
    assert emu.screen_size == (160, 144)
    assert emu.screenshot().size == (160, 144)
    assert len(emu.frame_rgb()) == 160 * 144 * 3


def test_fake_game_screen_size_and_frames():
    emu = FakeEmulator(game=TINY)
    assert emu.screen_size == (2, 2)
    assert emu.screenshot().size == (2, 2)
    assert len(emu.frame_rgb()) == 2 * 2 * 3


def test_fake_game_accepts_its_buttons():
    emu = FakeEmulator(game=TINY)
    for name in TINY.buttons:
        emu.press(Button(name))
    assert emu.presses == [Button.A, Button.B, Button.START]


def test_fake_game_rejects_a_button_it_does_not_have():
    emu = FakeEmulator(game=TINY)
    with pytest.raises(ValueError, match="'up' is not a button of tiny-game"):
        emu.press(Button.UP)
    assert emu.presses == []


def test_fake_game_none_still_ticks():
    emu = FakeEmulator(game=TINY)
    emu.press(Button.NONE)
    assert emu.presses == []
    assert emu.frames == 8 + 16


def test_red_accepts_every_button_except_none():
    emu = FakeEmulator()
    for b in Button:
        if b is not Button.NONE:
            emu.press(b)
    assert emu.presses == [b for b in Button if b is not Button.NONE]
