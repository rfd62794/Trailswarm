"""``rom_sprite`` avatars: an adapter over an injected sprite provider, with no import
of the world package at import time (a worktree has no image data to decode anyway).

Nothing here runs unless the preset's avatar is ``rom_sprite`` AND the caller supplies
bytes; the game-agnostic viewer tests inject a fake provider instead.
"""
from __future__ import annotations

import numpy as np


class RomAvatars:
    """``provider(facing, phase, colour) -> RGBA array | None``; a lookup error means
    "no picture" and the caller falls back to the drawn square."""

    def __init__(self, provider) -> None:
        self.provider = provider

    def get(self, agent: str, facing: str, phase: int, colour):
        try:
            return self.provider(facing, phase, colour)
        except (ValueError, IndexError, KeyError):
            return None


def book_provider(rom_bytes: bytes):
    """A provider backed by ``world.draw.SpriteBook`` (imported inside so importing this
    module stays free of the world package and image data)."""
    from pokeagent.atlas.sprites import PLAYER
    from pokeagent.world.draw import SpriteBook
    book = SpriteBook(rom_bytes)

    def provider(facing: str, phase: int, colour):
        return np.asarray(book.image(PLAYER, facing, phase, colour), dtype=np.uint8)

    return provider
