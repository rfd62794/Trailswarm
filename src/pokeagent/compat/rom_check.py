"""ROM-level Red-vs-Blue checks (bytes in, dicts out; ROM contents are read, never kept, copied or printed).

* ``compare_headers``: the 248-entry map-header table decodes identically (tileset, size, connections, warps,
  signs, objects) - the same headers the explorer's atlas reads.
* ``symbol_operand_counts``: for each WRAM symbol, how many times its little-endian address appears as a
  3-byte ``op lo hi`` operand pattern in the ROM. Both builds come from one engine, so the counts must agree;
  a symbol whose count differs beyond ``tolerance`` is reported. This is a static proxy for "same WRAM layout".
* ``wild_overlay``: the version-exclusive encounter differences, as a family kb overlay.
"""
from __future__ import annotations

from dataclasses import asdict

from pokeagent.atlas.rom_maps import all_headers
from pokeagent.family.kb_overlay import build_overlay

# Opcodes taking a 16-bit address operand: LD A,(nn) / LD (nn),A / LD HL,nn / LD DE,nn / LD BC,nn / LD SP,nn / LD (nn),SP
_OPS = (0xFA, 0xEA, 0x21, 0x11, 0x01, 0x31, 0x08)


# MapHeader fields that are raw ROM file offsets: a layout shift moves them without changing the map.
# Audit of the decoded header (rom_maps.header): the ONLY raw pointer kept is ``blocks_ptr``. The text, script,
# object and connection-source/dest/window pointers are followed during decoding and never stored; what is stored
# is what they point to (warps, signs, objects with text *ids*, connection map/offset/length, border block), all
# of which are compared by value. So ``blocks_ptr`` is excluded from the header compare and its target is
# compared separately as block CONTENT.
POINTER_FIELDS = ("blocks_ptr",)


def _without_pointers(h) -> dict:
    d = asdict(h)
    for f in POINTER_FIELDS:
        d.pop(f, None)
    return d


def compare_headers(red: bytes, blue: bytes) -> dict:
    """``{"maps_red", "maps_blue", "different", "only_red", "only_blue", "block_differences", "pointer_shifts"}``.

    ``different``: map ids whose decoded headers differ ignoring raw pointers. ``block_differences``: ids whose
    ``w*h`` block bytes (read at each ROM's ``blocks_ptr``) differ. ``pointer_shifts``: how many maps have a
    different ``blocks_ptr`` but identical content; a benign layout shift, never counted as a difference."""
    r, b = all_headers(red), all_headers(blue)
    common = sorted(set(r) & set(b))
    return {"maps_red": len(r), "maps_blue": len(b),
            "different": [i for i in common if _without_pointers(r[i]) != _without_pointers(b[i])],
            "only_red": sorted(set(r) - set(b)), "only_blue": sorted(set(b) - set(r)),
            "block_differences": [i for i in common if r[i].blocks(red) != b[i].blocks(blue)],
            "pointer_shifts": sum(1 for i in common if r[i].blocks_ptr != b[i].blocks_ptr
                                  and r[i].blocks(red) == b[i].blocks(blue))}


def symbol_operand_counts(rom: bytes, symbols: dict[str, int]) -> dict[str, int]:
    out = {}
    for name, addr in symbols.items():
        lo, hi = addr & 0xFF, addr >> 8
        out[name] = sum(1 for op in _OPS for i in _find_all(rom, bytes((op, lo, hi))))
    return out


def _find_all(data: bytes, pat: bytes):
    i = data.find(pat)
    while i != -1:
        yield i
        i = data.find(pat, i + 1)


def compare_symbol_counts(red: dict[str, int], blue: dict[str, int], tolerance: float = 0.02) -> dict:
    """Symbols whose operand counts differ by more than ``tolerance`` (relative; a zero count must match exactly)."""
    bad = {n: (red[n], blue.get(n, 0)) for n in red
           if red[n] != blue.get(n, 0) and abs(red[n] - blue.get(n, 0)) > tolerance * red[n]}
    return {"symbols": len(red), "mismatched": bad, "unreferenced": sorted(n for n, c in red.items() if c == 0)}


def wild_overlay(red_wild: dict, blue_wild: dict) -> dict:
    """Blue's wild tables (``rom_world.wild`` shape, map id -> record) as an overlay on Red's: only differing maps.
    Keys are stringified so the overlay survives a JSON round trip."""
    return build_overlay({"wild_by_map": {str(k): v for k, v in red_wild.items()}},
                         {"wild_by_map": {str(k): v for k, v in blue_wild.items()}})
