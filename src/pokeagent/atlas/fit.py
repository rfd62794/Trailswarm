"""Fit interiors into their building (pure, cells): footprint detection, scale choice, per-building transform.

A building's footprint is the contiguous non-walkable cell block above its door (cell = 2x2 tiles; walkable comes from the
tileset collision list). If the flood runs into the search limit it has merged with scenery (trees, fences), so a fixed
rectangle above the door is used instead. The scale is the largest of SCALES that fits, never below MIN_SCALE; the
interior then overflows with its frame. Floors above/below inherit the building's scale and line up on their stairs.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from pokeagent.atlas.anchor import Anchor
from pokeagent.atlas.rom_maps import BANK, MapHeader
from pokeagent.atlas.tiles import load_tileset, tileset_entry
from pokeagent.atlas.world import WorldLayout, Xform

SCALES = (1.0, 0.75, 0.5)
MIN_SCALE = 0.5
FALLBACK = (6, 4)              # cells wide, tall (door row included) when the footprint cannot be read
LIMIT_W, LIMIT_H = 7, 9        # flood reach from the door: cells sideways, cells up


def walk_cells(rom: bytes, hd: MapHeader) -> np.ndarray:
    """(h*2, w*2) bool: cell walkable by the tileset collision list (bottom-left tile of each 2x2 step, as the game does)."""
    bank, _bs, _gfx = tileset_entry(rom, hd.tileset)
    e = 0xC7BE + 12 * hd.tileset
    ptr = rom[e + 5] | rom[e + 6] << 8
    o, ids = bank * BANK - BANK + ptr, set()
    while o < len(rom) and rom[o] != 0xFF and len(ids) < 256:
        ids.add(rom[o])
        o += 1
    bs = load_tileset(rom, hd.tileset).blockset
    blocks = np.frombuffer(hd.blocks(rom), dtype=np.uint8)
    if blocks.size < hd.w * hd.h:
        blocks = np.pad(blocks, (0, hd.w * hd.h - blocks.size))
    blocks = blocks.reshape(hd.h, hd.w)
    tile = bs[blocks.astype(np.intp) % len(bs)][:, :, [1, 3]][:, :, :, [0, 2]]          # (h, w, 2, 2): rows 1,3 of the 4x4, cols 0,2
    tile = tile.transpose(0, 2, 1, 3).reshape(hd.h * 2, hd.w * 2)
    return np.isin(tile, list(ids))


def footprint(walk: np.ndarray | None, door: tuple[int, int]) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) cells, end-exclusive, of the building whose door is ``door``; includes the door row."""
    dx, dy = door
    fb = (dx - FALLBACK[0] // 2, dy + 1 - FALLBACK[1], dx - FALLBACK[0] // 2 + FALLBACK[0], dy + 1)
    if walk is None or not (0 <= dy - 1 < walk.shape[0] and 0 <= dx < walk.shape[1]) or walk[dy - 1, dx]:
        return fb
    seen, stack = {(dx, dy - 1)}, [(dx, dy - 1)]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in seen or not (0 <= ny < walk.shape[0] and 0 <= nx < walk.shape[1]) or walk[ny, nx] or ny > dy - 1:
                continue
            if abs(nx - dx) > LIMIT_W or dy - ny > LIMIT_H:
                return fb                                      # ran into the limit: merged with scenery
            seen.add((nx, ny))
            stack.append((nx, ny))
    xs, ys = [p[0] for p in seen], [p[1] for p in seen]
    return min(xs), min(ys), max(xs) + 1, dy + 1


def choose_scale(w: float, h: float, fw: float, fh: float) -> float:
    """Largest of SCALES with the interior (w x h cells) inside fw x fh; MIN_SCALE when none fits."""
    for s in SCALES:
        if w * s <= fw and h * s <= fh:
            return s
    return MIN_SCALE


def build_xforms(anchors: dict[int, Anchor], layout: WorldLayout, walk_of: Callable[[int], np.ndarray | None],
                 fit: bool = True) -> dict[int, Xform]:
    """Transform of every anchored interior. ``fit=False``: full size on the door; ``fit``: scaled into the footprint."""
    out: dict[int, Xform] = {}
    for m in sorted(anchors, key=lambda k: (anchors[k].depth, k)):
        a, p = anchors[m], layout.places[m]
        if not fit:
            out[m] = Xform(float(a.x), float(a.y), 1.0)
        elif a.parent in out:                                   # another floor: same scale, lined up on the stair tile
            t = out[a.parent]
            out[m] = Xform(t.ox + (a.via[0] - a.entry[0]) * t.s, t.oy + (a.via[1] - a.entry[1]) * t.s, t.s)
        else:
            par = layout.places[a.parent]
            x0, y0, x1, y1 = footprint(walk_of(a.parent), a.via)
            s = choose_scale(p.w, p.h, x1 - x0, y1 - y0)
            ox, oy = par.x + a.via[0] - a.entry[0] * s, par.y + a.via[1] - a.entry[1] * s
            if p.w * s <= x1 - x0:                              # keep a fitting interior inside its building
                ox = min(max(ox, par.x + x0), par.x + x1 - p.w * s)
            if p.h * s <= y1 - y0:
                oy = min(max(oy, par.y + y0), par.y + y1 - p.h * s)
            out[m] = Xform(ox, oy, s)
    return out
