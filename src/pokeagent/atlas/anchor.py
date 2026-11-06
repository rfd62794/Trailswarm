"""Where does each interior belong in the outdoor world? (pure, cells)

A parent warp (x, y, dest_warp, dest_map) opens onto interior warp ``dest_warp`` (0-based in the ROM table): that interior
tile is where you arrive, so the interior is anchored with that tile on the parent's warp tile (the door). Stairs and
ladders chain the same way: a 2F is anchored on its 1F's stair tile, so floors line up. BFS starts from the stitched
outdoor maps over ROM warps; only when that is exhausted does it use learned warps ('x,y,DIR' -> [map, x, y] in
maps.json) to reach what is left. Interiors neither reaches stay in the inset grid.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pokeagent.atlas.rom_maps import MapHeader
from pokeagent.atlas.world import WorldLayout

LAST_MAP = 255


@dataclass(frozen=True)
class Anchor:
    map: int
    x: int                      # world cell of the interior's top-left at full size
    y: int
    depth: int                  # 1 = opens onto the outdoors, 2 = a floor below/above that, ...
    parent: int
    source: str                 # "rom" | "learned"
    via: tuple[int, int]        # the parent's warp tile (the door / stair)
    entry: tuple[int, int]      # the interior tile that lands on ``via``


def entry_tile(hd: MapHeader, dest_warp: int, parent: int) -> tuple[int, int] | None:
    """Where a warp lands in ``hd``: the dest warp's tile, else its first exit back to ``parent``."""
    if 0 <= dest_warp < len(hd.warps):
        return hd.warps[dest_warp][0], hd.warps[dest_warp][1]
    for x, y, _dw, dm in hd.warps:
        if dm in (parent, LAST_MAP):
            return x, y
    return None


def _learned(model: dict | None, m: int):
    for key, dest in ((model or {}).get("maps", {}).get(str(m), {}).get("warps") or {}).items():
        try:
            x, y = (int(v) for v in key.split(",")[:2])
            yield x, y, int(dest[0]), (int(dest[1]), int(dest[2]))
        except (ValueError, IndexError, TypeError):
            continue


def anchor_interiors(headers: dict[int, MapHeader], layout: WorldLayout, model: dict | None = None) -> dict[int, Anchor]:
    interior = {m for m, p in layout.places.items() if p.interior}
    outdoor = sorted(set(layout.places) - interior)
    anchors: dict[int, Anchor] = {}

    def origin(m: int) -> tuple[int, int]:
        if m in anchors:
            return anchors[m].x, anchors[m].y
        return layout.places[m].x, layout.places[m].y

    def put(parent: int, x: int, y: int, child: int, entry: tuple[int, int], src: str) -> None:
        ox, oy = origin(parent)
        depth = anchors[parent].depth + 1 if parent in anchors else 1
        anchors[child] = Anchor(child, ox + x - entry[0], oy + y - entry[1], depth, parent, src, (x, y), entry)

    queue = deque(outdoor)
    while True:
        while queue:
            m = queue.popleft()
            for x, y, dw, dm in headers[m].warps if m in headers else ():
                if dm in interior and dm not in anchors and dm in headers:
                    e = entry_tile(headers[dm], dw, m)
                    if e is not None:
                        put(m, x, y, dm, e, "rom")
                        queue.append(dm)
        found = False
        for m in outdoor + sorted(anchors):
            for x, y, dm, e in _learned(model, m):
                if dm in interior and dm not in anchors:
                    put(m, x, y, dm, e, "learned")
                    queue.append(dm)
                    found = True
                    break
            if found:
                break
        if not found:
            return anchors
