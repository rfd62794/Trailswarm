"""The label types a LabelSource emits for one rendered frame, and the per-game seam."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SpriteBox:
    """One labelled sprite: x, y, w, h is the screen-pixel crop box; pos is the entity's map-tile
    position for the positions log (None when the source has no map position for it)."""
    label: int
    coarse: str
    x: int
    y: int
    w: int
    h: int
    ident: str
    move: int
    pos: tuple[int, int] | None = None


@dataclass(frozen=True)
class TileCell:
    """One visible background cell: the tile id and its screen-pixel top-left (always a full 8x8)."""
    label: int
    x: int
    y: int


@dataclass(frozen=True)
class FrameLabels:
    """Everything a source reads for one frame: area string, bank (tileset) or None, player map-tile
    pair, coarse cell bucket string, sprite boxes, background cells, and skip."""
    area: str
    bank: int | None
    player: tuple[int, int] | None
    cell: str
    sprites: tuple[SpriteBox, ...] = field(default=())
    tiles: tuple[TileCell, ...] = field(default=())
    skip: bool = False


class LabelSource(Protocol):
    """The per-game seam record.py drives; adding a game is one module plus one registry line."""
    name: str                      # e.g. "pokemon-red"
    boot_presses: tuple            # (button name, hold, settle) presses to reach play from a cold boot

    def read(self, emu) -> FrameLabels:
        """Everything for the frame just rendered; called right after a rendered tick."""
        ...
