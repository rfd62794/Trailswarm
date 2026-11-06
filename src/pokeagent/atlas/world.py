"""Stitch maps into one world layout: outdoor maps by ROM connection records, interiors in a labelled inset grid.

Units are cells (2x2 tiles = 16 px), the agent's own (x, y) coordinate system. Connection offsets are in blocks (1 block =
2 cells): N/S neighbours sit at x + offset, E/W at y + offset. BFS from Pallet Town (map 0) places every connected map once;
maps the BFS never reaches (interiors, caves, unused ids) go in an inset grid below the world, each linked back to the
warp that leads to it (multi-source BFS over warp records, starting from the stitched maps).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

from pokeagent.atlas.rom_maps import MapHeader

CELL = 16
MARGIN = 6          # cells of border drawn around the stitched world (3 blocks, what the game shows)
LABEL = 1           # cell rows of title above each inset
GAP = 2
MIN_ROW = 120       # inset rows wrap at max(world width, this) cells


@dataclass(frozen=True)
class Place:
    x: int
    y: int
    w: int
    h: int
    interior: bool


class Xform(NamedTuple):
    """Where an interior is painted in place: top-left (cells, may be fractional) and scale (1.0 = full size)."""
    ox: float
    oy: float
    s: float


@dataclass
class WorldLayout:
    places: dict[int, Place]
    width: int                                  # cells, whole canvas
    height: int
    outdoor_height: int                         # cells; interiors start below this
    entrances: dict[int, tuple[int, int, int]] = field(default_factory=dict)   # interior -> (parent map, x, y)
    pins: dict[int, tuple[int, int]] = field(default_factory=dict)    # in-place views: interior shown only as its door cell
    xf: dict[int, Xform] = field(default_factory=dict)                # in-place views: interior painted at this transform
    z: dict[int, int] = field(default_factory=dict)                   # in-place views: draw rank (higher = on top)

    def to_world(self, map_id: int, x: int, y: int) -> tuple[int, int]:
        """Top-left pixel of cell (x, y) of ``map_id`` on the world image."""
        if map_id in self.pins:
            return self.pins[map_id][0] * CELL, self.pins[map_id][1] * CELL
        if map_id in self.xf:
            t = self.xf[map_id]
            return round((t.ox + x * t.s) * CELL), round((t.oy + y * t.s) * CELL)
        p = self.places[map_id]
        return (p.x + x) * CELL, (p.y + y) * CELL

    @property
    def size_px(self) -> tuple[int, int]:
        return self.width * CELL, self.height * CELL


def stitch(headers: dict[int, MapHeader], start: int = 0) -> dict[int, tuple[int, int]]:
    """Block-coordinate origin of every map reachable from ``start`` through connection records."""
    pos = {start: (0, 0)}
    q = deque([start])
    while q:
        m = q.popleft()
        hd, (cx, cy) = headers[m], pos[m]
        for c in hd.connections:
            nb = headers.get(c.target)
            if nb is None or c.target in pos:
                continue
            if c.direction == "N":
                pos[c.target] = (cx + c.offset, cy - nb.h)
            elif c.direction == "S":
                pos[c.target] = (cx + c.offset, cy + hd.h)
            elif c.direction == "W":
                pos[c.target] = (cx - nb.w, cy + c.offset)
            else:
                pos[c.target] = (cx + hd.w, cy + c.offset)
            q.append(c.target)
    return pos


def entrances(headers: dict[int, MapHeader], roots: set[int]) -> tuple[dict[int, tuple[int, int, int]], list[int]]:
    """Warp BFS from ``roots``: (child -> (parent, x, y) of the warp leading in, discovery order of the children)."""
    parent: dict[int, tuple[int, int, int]] = {}
    order: list[int] = []
    q = deque(sorted(roots))
    seen = set(roots)
    while q:
        m = q.popleft()
        for x, y, _dw, dm in headers[m].warps:
            if dm in headers and dm not in seen:
                seen.add(dm)
                parent[dm] = (m, x, y)
                order.append(dm)
                q.append(dm)
    return parent, order


def build_layout(headers: dict[int, MapHeader], start: int = 0) -> WorldLayout:
    blocks = stitch(headers, start)
    minx = min(bx for bx, _ in blocks.values())
    miny = min(by for _, by in blocks.values())
    places: dict[int, Place] = {}
    for m, (bx, by) in blocks.items():
        hd = headers[m]
        places[m] = Place((bx - minx) * 2 + MARGIN, (by - miny) * 2 + MARGIN, hd.w * 2, hd.h * 2, False)
    width = max(p.x + p.w for p in places.values()) + MARGIN
    out_h = max(p.y + p.h for p in places.values()) + MARGIN
    parent, order = entrances(headers, set(blocks))
    rest = order + [m for m in sorted(headers) if m not in blocks and m not in parent]
    row_w, x, y, row_h = max(width, MIN_ROW), GAP, out_h + GAP, 0
    for m in rest:
        w, h = headers[m].w * 2, headers[m].h * 2
        if x + w + GAP > row_w and x > GAP:
            x, y, row_h = GAP, y + row_h + GAP, 0
        places[m] = Place(x, y + LABEL, w, h, True)
        x, row_h = x + w + GAP, max(row_h, h + LABEL)
    return WorldLayout(places, max(width, row_w), y + row_h + GAP, out_h, parent)
