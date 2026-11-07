"""Tileset graphics and blocksets from the ROM (pure functions on bytes).

TILESETS is the 24-entry, 12-byte-per-entry table at 0xC7BE: bank, blockset ptr, gfx ptr, collision ptr, 3 counter tiles,
grass tile, animation. Located by scanning the whole ROM for 24 consecutive plausible entries (bank 1..0x3F, pointers in
0x4000-0x7FFF); exactly one hit, and entry 0 is bank 0x19, blockset 0x45E0, gfx 0x4000 (the Overworld, matching pret's
tileset_headers.asm). Tile graphics are uncompressed 2bpp (16 bytes per 8x8 tile, low plane byte then high plane byte per
row, bit 7 = leftmost pixel); a tileset loads 0x60 tiles. A block is 16 bytes: 4x4 tile ids, row major.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TILESETS, NUM_TILESETS, ENTRY = 0xC7BE, 24, 12
BANK = 0x4000
TILE_COUNT, BLOCK_BYTES, MAX_BLOCKS = 0x60, 16, 256
GREY = np.array([255, 170, 85, 0], dtype=np.uint8)     # Gen 1 BGP 0xE4: white, light, dark, black


@dataclass(frozen=True)
class Tileset:
    index: int
    blockset: np.ndarray      # (n_blocks, 4, 4) tile ids
    tiles: np.ndarray         # (256, 8, 8) uint8 shade index 0..3 (tiles past the loaded set are 0 = white)


def decode_tiles(raw: bytes, count: int = 256) -> np.ndarray:
    """Decode 2bpp tile data to a (count, 8, 8) array of shade indexes; missing tiles stay 0."""
    out = np.zeros((count, 8, 8), dtype=np.uint8)
    n = min(count, len(raw) // 16)
    if n:
        b = np.frombuffer(raw[:n * 16], dtype=np.uint8).reshape(n, 8, 2)
        bits = np.arange(7, -1, -1, dtype=np.uint8)
        lo = (b[:, :, 0, None] >> bits) & 1
        hi = (b[:, :, 1, None] >> bits) & 1
        out[:n] = hi << 1 | lo
    return out


def decode_blockset(raw: bytes) -> np.ndarray:
    """(n, 4, 4) tile ids from 16 bytes per block."""
    n = len(raw) // BLOCK_BYTES
    return np.frombuffer(raw[:n * BLOCK_BYTES], dtype=np.uint8).reshape(n, 4, 4).copy()


def tileset_entry(d: bytes, index: int) -> tuple[int, int, int]:
    """(bank, blockset ptr, gfx ptr) of tileset ``index``."""
    e = d[TILESETS + ENTRY * index:TILESETS + ENTRY * (index + 1)]
    return e[0], e[1] | e[2] << 8, e[3] | e[4] << 8


def load_tileset(d: bytes, index: int) -> Tileset:
    bank, bptr, gptr = tileset_entry(d, index)
    base = bank * BANK - BANK
    blocks = d[base + bptr:base + bptr + MAX_BLOCKS * BLOCK_BYTES]
    gfx = d[base + gptr:base + gptr + TILE_COUNT * 16]
    return Tileset(index, decode_blockset(blocks), decode_tiles(gfx))


def block_image(ts: Tileset, block_id: int) -> np.ndarray:
    """(32, 32) shade indexes for one block."""
    ids = ts.blockset[block_id % len(ts.blockset)]
    return ts.tiles[ids].transpose(0, 2, 1, 3).reshape(32, 32)
