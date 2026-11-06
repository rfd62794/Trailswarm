"""Read map headers, connections and warps straight from the ROM (verify a map id before using it).

    uv run python tools/rom_maps.py 3 15 59 64 65 35 36 88      # ids in decimal or 0x hex

MapHeaderPointers is the 248-entry table at 0x01AE (bank 0); MapHeaderBanks is the byte table at 0xC23D. Both were located
by search (pointer 0 -> header 00 09 0A = Pallet Town 10x9, pointer 1 -> 00 12 14 = Viridian 20x18) and re-checked: 224 of
248 entries decode to a sane header. Header: tileset, height, width (blocks), map ptr, text ptr, script ptr, connection
flags (N=8 S=4 W=2 E=1; 11 bytes each: target map first), object ptr -> border, n warps, then (y, x, dest warp, dest map)
per warp; dest map 255 = the map you came from. Printed warps are (x, y) tile coordinates.
"""
from __future__ import annotations

import sys
from pathlib import Path

PTRS, BANKS = 0x01AE, 0xC23D


def load(rom: str = "roms/Pokemon Red.gb") -> bytes:
    return Path(rom).read_bytes()


def header(d: bytes, i: int) -> dict:
    b, ptr = d[BANKS + i], d[PTRS + 2 * i] | d[PTRS + 2 * i + 1] << 8
    o = b * 0x4000 + ptr - 0x4000
    q, conns = o + 10, {}
    for name, bit in (("N", 8), ("S", 4), ("W", 2), ("E", 1)):
        if d[o + 9] & bit:
            conns[name] = d[q]; q += 11
    oo = b * 0x4000 + (d[q] | d[q + 1] << 8) - 0x4000
    warps = [(d[oo + 3 + 4 * k], d[oo + 2 + 4 * k], d[oo + 4 + 4 * k], d[oo + 5 + 4 * k]) for k in range(d[oo + 1])]
    return {"tileset": d[o], "h": d[o + 1], "w": d[o + 2], "connections": conns, "warps": warps}


def main(argv: list[str]) -> int:
    d = load()
    for a in argv or ["3"]:
        i = int(a, 0)
        print(f"0x{i:02X} ({i}):", header(d, i))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
