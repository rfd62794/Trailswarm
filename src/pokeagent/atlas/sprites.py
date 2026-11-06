"""Overworld sprite sheets from the ROM (pure functions on bytes): the player and every NPC picture.

SPRITE_SHEETS is the 4-byte-per-entry table (pointer, size byte, bank) found by scanning the ROM for a long run of plausible
entries; entry 0 is SPRITE_RED and decodes to the player. The size byte is the *standing* graphics only (12 tiles = 3 frames:
down, up, left); sprites that walk keep 12 more tiles right after (walk down, up, left) - the next entry's pointer is then 0x180
past this one. Each frame is 2x2 tiles (16x16), tiles row major. Right-facing is the left frame mirrored; the second walk
step of down/up is the walk frame mirrored. Shade 0 (white) is transparent on the overworld.
"""
from __future__ import annotations

import numpy as np

from pokeagent.atlas.tiles import GREY, decode_tiles

SPRITE_SHEETS = 97063       # 0x17AA7
ENTRIES, BANK = 70, 0x4000
PLAYER = 1                  # SPRITE_RED
FACING = {"DOWN": 0, "UP": 1, "LEFT": 2, "RIGHT": 2}


def _entry(rom: bytes, sprite_id: int) -> tuple[int, int, int]:
    e = rom[SPRITE_SHEETS + 4 * (sprite_id - 1):SPRITE_SHEETS + 4 * sprite_id]
    return e[0] | e[1] << 8, e[2], e[3]


def decode_frames(raw: bytes, tiles: int) -> np.ndarray:
    """(n, 16, 16) shade indexes from ``tiles`` 2bpp tiles (4 per frame, row major)."""
    t = decode_tiles(raw, tiles)[:tiles // 4 * 4].reshape(-1, 4, 8, 8)
    top, bot = np.concatenate([t[:, 0], t[:, 1]], axis=2), np.concatenate([t[:, 2], t[:, 3]], axis=2)
    return np.concatenate([top, bot], axis=1)


def sheet(rom: bytes, sprite_id: int) -> np.ndarray:
    """All frames of one overworld sprite: 6 (stand d/u/l, walk d/u/l) when it walks, else 3."""
    if not 1 <= sprite_id <= ENTRIES:
        raise ValueError(f"no such sprite {sprite_id}")
    ptr, size, bank = _entry(rom, sprite_id)
    off = bank * BANK - BANK + ptr
    walks = sprite_id < ENTRIES and _entry(rom, sprite_id + 1)[0] - ptr >= 2 * size and _entry(rom, sprite_id + 1)[2] == bank
    n = 2 * size if walks else size
    return decode_frames(rom[off:off + n], n // 16)


def pick_frame(frames: np.ndarray, facing: str, walk_phase: int = 0) -> np.ndarray:
    """The 16x16 shade image for ``facing`` ("UP"/"DOWN"/"LEFT"/"RIGHT"); ``walk_phase`` 1 / 2 = the two walk steps, 0 = standing."""
    k = FACING.get(facing, 0)
    k = k if k < len(frames) else 0
    img = frames[k]
    if walk_phase and len(frames) >= 6:
        img = frames[3 + k]
        if walk_phase == 2 and k < 2:
            img = img[:, ::-1]
    if facing == "RIGHT":
        img = img[:, ::-1]
    return img


def sprite_rgba(img: np.ndarray, outline: tuple[int, int, int] | None = None) -> np.ndarray:
    """(18, 18, 4) uint8: grey-shaded sprite (shade 0 transparent) with a 1 px ``outline`` ring in an agent colour."""
    out = np.zeros((18, 18, 4), dtype=np.uint8)
    solid = img > 0
    body = out[1:17, 1:17]
    body[solid, :3] = GREY[img[solid]][:, None]
    body[solid, 3] = 255
    if outline is not None:
        s = np.pad(solid, 1)
        ring = np.zeros_like(s)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ring |= np.roll(np.roll(s, dy, 0), dx, 1)
        ring &= ~s
        out[ring, :3] = outline
        out[ring, 3] = 255
    return out
