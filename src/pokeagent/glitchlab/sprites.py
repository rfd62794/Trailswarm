"""Trainer sprites on the current map, read from RAM only (sprite tables + wMapSpriteExtraData)."""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.explorer.anomaly_sprites import HIDDEN, SPRITE_SLOTS, SPRITE_STATE1, SPRITE_STATE2

MAP_SPRITE_EXTRA = 0xD504   # wMapSpriteExtraData: 2 bytes per sprite, read by EngageMapTrainer as (slot - 1) * 2
TRAINER_CLASS_MIN = 200     # OPP_ID_OFFSET: a class byte at or above it is a trainer (items/NPCs sit below)
FACINGS = {0: "down", 4: "up", 8: "left", 0xC: "right"}   # raw SPRITESTATEDATA1_FACINGDIRECTION


@dataclass(frozen=True)
class TrainerSprite:
    """One visible trainer sprite: ``x, y`` in map tiles, ``facing`` None when the raw byte is unrecognised."""

    slot: int
    cls: int
    trainer_set: int
    x: int
    y: int
    facing: str | None


def read_trainer_sprites(emu) -> list[TrainerSprite]:
    """Slots 1..15 that are visible and whose map-sprite class byte is a trainer class."""
    out = []
    for i in SPRITE_SLOTS:
        base = SPRITE_STATE1 + 16 * i
        if not emu.read(base) or emu.read(base + 2) == HIDDEN:
            continue
        extra = MAP_SPRITE_EXTRA + (i - 1) * 2
        cls = emu.read(extra)
        if cls < TRAINER_CLASS_MIN:
            continue
        out.append(TrainerSprite(slot=i, cls=cls, trainer_set=emu.read(extra + 1),
                                 x=emu.read(SPRITE_STATE2 + 16 * i + 5) - 4,
                                 y=emu.read(SPRITE_STATE2 + 16 * i + 4) - 4,
                                 facing=FACINGS.get(emu.read(base + 9))))
    return out
