"""read_trainer_sprites on a FakeEmulator memory: trainers only, tile math, facing decode."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.glitchlab import sprites as sp


def put(emu, slot, *, pic=1, image=0, cls, tset=3, tx=0, ty=0, facing=0):
    b = sp.SPRITE_STATE1 + 16 * slot
    emu.set(b, pic)
    emu.set(b + 2, image)
    emu.set(b + 9, facing)
    emu.set(sp.SPRITE_STATE2 + 16 * slot + 4, ty + 4)
    emu.set(sp.SPRITE_STATE2 + 16 * slot + 5, tx + 4)
    emu.set(sp.MAP_SPRITE_EXTRA + (slot - 1) * 2, cls)
    emu.set(sp.MAP_SPRITE_EXTRA + (slot - 1) * 2 + 1, tset)


def test_only_visible_trainer_sprites_are_returned():
    emu = FakeEmulator()
    put(emu, 1, cls=201, tx=10, ty=8, facing=0)
    put(emu, 2, cls=21, tx=3, ty=3)                 # item ball / NPC
    put(emu, 3, cls=205, image=0xFF)                # hidden
    put(emu, 4, cls=210, tx=5, ty=6, facing=7)      # unknown facing
    out = sp.read_trainer_sprites(emu)
    assert out == [sp.TrainerSprite(1, 201, 3, 10, 8, "down"), sp.TrainerSprite(4, 210, 3, 5, 6, None)]
    assert emu.memory[sp.SPRITE_STATE2 + 16 + 5] == 14 and emu.memory[sp.SPRITE_STATE2 + 16 + 4] == 12


def test_facing_decode():
    emu = FakeEmulator()
    for slot, raw in enumerate((0, 4, 8, 0xC), start=1):
        put(emu, slot, cls=200, facing=raw)
    assert [t.facing for t in sp.read_trainer_sprites(emu)] == ["down", "up", "left", "right"]
