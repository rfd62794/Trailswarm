"""Read map headers, connections and warps straight from the ROM (verify a map id before using it).

    uv run python tools/rom_maps.py 3 15 59 64 65 35 36 88      # ids in decimal or 0x hex

Thin CLI over ``pokeagent.atlas.rom_maps`` (which documents the table locations and header layout).
"""
from __future__ import annotations

import sys

from pokeagent.atlas.rom_maps import header, load, map_name


def main(argv: list[str]) -> int:
    d = load()
    for a in argv or ["3"]:
        i = int(a, 0)
        hd = header(d, i)
        print(f"0x{i:02X} ({i}) {map_name(i)}: tileset={hd.tileset} {hd.w}x{hd.h} blocks "
              f"conns={[(c.direction, c.target, c.offset) for c in hd.connections]} warps={hd.warps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
