"""Map headers, connections, warps, signs and objects straight from a Pokemon Red ROM (read-only, pure bytes).

MapHeaderPointers is the 248-entry table at 0x01AE (bank 0); MapHeaderBanks is the byte table at 0xC23D. Both were found
by search (pointer 0 -> header 00 09 0A = Pallet Town 10x9, pointer 1 -> 00 12 14 = Viridian 20x18) and re-checked against
pret's map_constants.asm: every decoded (h, w) matches. Header: tileset, height, width (blocks), blocks ptr, text ptr,
script ptr, connection flags (N=8 S=4 W=2 E=1), 11-byte connection records (map, src ptr, dest ptr, strip length,
neighbour width, y align, x align, window ptr), object ptr -> border block, warps (y, x, dest warp, dest map; 255 = the
map you came from), signs (y, x, text), objects (sprite, y+4, x+4, movement, range, text [+2 trainer bit 6, +1 item bit 7]).
Coordinates exposed here are (x, y) in 2x2-tile cells (the agent's coordinate system).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PTRS, BANKS, NUM_MAPS = 0x01AE, 0xC23D, 248
BANK = 0x4000
DIRS = (("N", 8), ("S", 4), ("W", 2), ("E", 1))
_NAMES_PATH = Path(__file__).with_name("map_names.json")


def load(rom: str | Path = "roms/Pokemon Red.gb") -> bytes:
    return Path(rom).read_bytes()


def map_name(map_id: int) -> str:
    try:
        return json.loads(_NAMES_PATH.read_text(encoding="utf-8")).get(str(map_id), f"MAP_{map_id:02X}")
    except OSError:
        return f"MAP_{map_id:02X}"


def _s8(v: int) -> int:
    return v - 256 if v > 127 else v


@dataclass(frozen=True)
class Connection:
    direction: str      # "N" | "S" | "W" | "E"
    target: int         # neighbour map id
    offset: int         # blocks: neighbour origin along the shared edge, relative to this map's origin
    length: int         # strip length in blocks


@dataclass
class MapHeader:
    map_id: int
    tileset: int
    h: int              # blocks
    w: int              # blocks
    blocks_ptr: int     # file offset of the h*w block-id bytes
    border: int
    connections: list[Connection] = field(default_factory=list)
    warps: list[tuple[int, int, int, int]] = field(default_factory=list)    # (x, y, dest_warp, dest_map)
    signs: list[tuple[int, int, int]] = field(default_factory=list)         # (x, y, text)
    objects: list[dict] = field(default_factory=list)                       # sprite, x, y, text, kind

    def blocks(self, rom: bytes) -> bytes:
        return rom[self.blocks_ptr:self.blocks_ptr + self.w * self.h]


def _parse_objects(d: bytes, p: int, n: int) -> list[dict]:
    out = []
    for _ in range(n):
        sprite, y, x, text = d[p], d[p + 1] - 4, d[p + 2] - 4, d[p + 5]
        kind, p = "npc", p + 6
        if text & 0x40:
            kind, p = "trainer", p + 2
        elif text & 0x80:
            kind, p = "item", p + 1
        out.append({"sprite": sprite, "x": x, "y": y, "text": text & 0x3F, "kind": kind})
    return out


def header(d: bytes, i: int) -> MapHeader:
    b, ptr = d[BANKS + i], d[PTRS + 2 * i] | d[PTRS + 2 * i + 1] << 8
    base = b * BANK - BANK
    o = base + ptr
    h, w, q, conns = d[o + 1], d[o + 2], o + 10, []
    for name, bit in DIRS:
        if d[o + 9] & bit:
            r = d[q:q + 11]
            raw = _s8(r[8] if name in "NS" else r[7])
            conns.append(Connection(name, r[0], -raw // 2, r[5]))
            q += 11
    oo = base + (d[q] | d[q + 1] << 8)
    nw = d[oo + 1]
    warps = [(d[oo + 3 + 4 * k], d[oo + 2 + 4 * k], d[oo + 4 + 4 * k], d[oo + 5 + 4 * k]) for k in range(nw)]
    sp = oo + 2 + 4 * nw
    ns = d[sp]
    signs = [(d[sp + 2 + 3 * k], d[sp + 1 + 3 * k], d[sp + 3 + 3 * k]) for k in range(ns)]
    op = sp + 1 + 3 * ns
    return MapHeader(i, d[o], h, w, base + (d[o + 3] | d[o + 4] << 8), d[oo], conns, warps, signs,
                     _parse_objects(d, op + 1, d[op]))


def is_sane(d: bytes, i: int) -> bool:
    """True when entry ``i`` decodes to a plausible header (unused map ids point at junk)."""
    b, ptr = d[BANKS + i], d[PTRS + 2 * i] | d[PTRS + 2 * i + 1] << 8
    if not (1 <= b < len(d) // BANK and BANK <= ptr < 2 * BANK):
        return False
    o = b * BANK - BANK + ptr
    return d[o] < 24 and 1 <= d[o + 1] <= 80 and 1 <= d[o + 2] <= 80 and BANK <= (d[o + 3] | d[o + 4] << 8) < 2 * BANK


def all_headers(d: bytes) -> dict[int, MapHeader]:
    """Every sane map header, keyed by map id."""
    out: dict[int, MapHeader] = {}
    for i in range(NUM_MAPS):
        try:
            if is_sane(d, i):
                out[i] = header(d, i)
        except IndexError:
            continue
    return out
