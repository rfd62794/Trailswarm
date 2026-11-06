"""maps_summary and map_view: the whole-model overview and one map's legend-glyph grid."""
from __future__ import annotations

from pokeagent.brain.common import known_tiles, mid_key, npc_tiles, parse_tile
from pokeagent.explorer import legend, tilekind

OVERLAYS = ("visits", "encounters", "fails")

_MAP_FIELDS = ("visited", "blocked", "warps", "warp_cand", "jumps", "interactions",
               "npcs", "encounters", "fails", "outcomes", "demos")


def _count(d: dict, sect: str) -> int:
    v = d.get(sect)
    return len(v) if v else 0


def maps_summary(data: dict) -> dict:
    """Per-map fact counts plus the global learned tables, for 'what does the model know'."""
    maps = data.get("maps") or {}
    out_maps = {}
    totals = {k: 0 for k in _MAP_FIELDS}
    totals["tiles"] = 0
    for mid in sorted(maps, key=mid_key):
        d = maps[mid] or {}
        entry = {sect: _count(d, sect) for sect in _MAP_FIELDS}
        entry["last_seen"] = d.get("last_seen", 0)
        out_maps[mid] = entry
        for sect in _MAP_FIELDS:
            totals[sect] += entry[sect]
        totals["tiles"] += len(known_tiles(d))
    return {
        "maps": out_maps,
        "totals": {"maps": len(maps), **totals},
        "tile_types": {ts: len(t) for ts, t in sorted((data.get("tile_types") or {}).items())},
        "grass_ids": {ts: len(t) for ts, t in sorted((data.get("grass_ids") or {}).items())},
        "bad_warps": len(data.get("bad_warps") or []),
        "beats": len(data.get("beats") or {}),
        "battle_lessons": len(data.get("battle_lessons") or {}),
        "items": len(data.get("items") or []),
        "events": len(data.get("events") or []),
        "catches": len(data.get("catches") or []),
        "updated": data.get("updated"),
    }


def _outcome_cells(d: dict, stage: str) -> dict:
    """Per-tile outcome progress for one goal stage: {"x,y": {"n","progress","best"}}."""
    cells: dict = {}
    for key, stages in (d.get("outcomes") or {}).items():
        p = parse_tile(key)
        if p is None:
            continue
        agg = cells.setdefault(p, {"n": 0, "progress": 0, "best": None})
        for stats in (stages or {}).values():
            s = (stats or {}).get(stage)
            if not s:
                continue
            agg["n"] += s.get("n", 0)
            agg["progress"] += s.get("progress", 0)
            best = s.get("best")
            if best is not None and (agg["best"] is None or best < agg["best"]):
                agg["best"] = best
    return {p: v for p, v in cells.items() if v["n"]}


def overlay_cells(d: dict, overlay: str) -> dict:
    """``{(x, y): value}`` for one overlay mode; only non-zero cells."""
    if overlay == "visits":
        return {p: n for k, n in (d.get("visited") or {}).items()
                if (p := parse_tile(k)) is not None and n}
    if overlay == "encounters":
        return {p: n for k, n in (d.get("encounters") or {}).items()
                if (p := parse_tile(k)) is not None and n}
    if overlay == "fails":
        cells: dict = {}
        for k, n in (d.get("fails") or {}).items():
            p = parse_tile(k)
            if p is not None and n:
                cells[p] = cells.get(p, 0) + n
        return cells
    if overlay.startswith("outcomes:"):
        return _outcome_cells(d, overlay.split(":", 1)[1])
    raise ValueError(f"unknown overlay {overlay!r}; use visits|encounters|fails|outcomes:<goal>")


def _empty_view(mid: str, overlay, error: str | None = None) -> dict:
    out = {"map": mid, "bounds": None, "width": 0, "height": 0, "rows": [], "legend": "",
           "kind_counts": {}, "tiles_known": 0, "overlay": {"mode": overlay, "cells": {}}}
    if error:
        out["error"] = error
    return out


def map_view(data: dict, map_id, overlay: str | None = None) -> dict:
    """Legend-glyph rows for everything memory knows on one map, plus per-tile overlay values.

    ``overlay``: visits | encounters | fails | outcomes:<goal-stage>. Cells are keyed "x,y".
    """
    mid = str(map_id)
    d = (data.get("maps") or {}).get(mid)
    if d is None:
        return _empty_view(mid, overlay, "map not in memory")
    tiles = known_tiles(d)
    if not tiles:
        return _empty_view(mid, overlay)
    if overlay is not None:
        overlay_cells(d, overlay)  # validates the mode early
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    min_x, max_x, min_y, max_y = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    tile_types = data.get("tile_types") or {}
    grass_ids = data.get("grass_ids") or {}
    trainers = tilekind.trainer_tiles(d)
    npcs_here = npc_tiles(d)
    kinds: dict = {}
    rows = []
    for y in range(min_y, max_y + 1):
        line = ""
        for x in range(min_x, max_x + 1):
            kind = tilekind.classify(d, tile_types, grass_ids, 0, x, y, None, npcs_here, trainers)
            kinds[kind] = kinds.get(kind, 0) + 1
            line += legend.glyph(kind, tilekind.ledge_dir(d, x, y) if kind == "ledge" else None)
        rows.append(line)
    cells = overlay_cells(d, overlay) if overlay else {}
    return {
        "map": mid,
        "bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
        "width": max_x - min_x + 1,
        "height": max_y - min_y + 1,
        "rows": rows,
        "legend": legend.line(kinds),
        "kind_counts": kinds,
        "tiles_known": len(tiles),
        "overlay": {"mode": overlay,
                    "cells": {f"{x},{y}": v for (x, y), v in sorted(cells.items())}},
    }
