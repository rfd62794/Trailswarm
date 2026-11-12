"""Allow-list export of map progress (walkable tiles, blocked edges, warps) from a maps.json document.

Every output value is rebuilt from parsed integers and the fixed DIRS / GAMES words; no string, list
or dict from the input is ever copied into the output, so text and unknown fields cannot leak.
See docs/directives/Progress_Export_Sanitized_Directive.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCHEMA_VERSION = 1
KIND = "trailswarm-progress-export"
GAMES = ("pokemon-red", "pokemon-blue")
DIRS = ("UP", "DOWN", "LEFT", "RIGHT")
OUTPUT_MAP_FIELDS = ("walkable", "blocked", "warps", "stats")

_MAP_ID = re.compile(r"\d{1,3}", re.ASCII)
_TILE = re.compile(r"(\d{1,3}),(\d{1,3})", re.ASCII)
_EDGE = re.compile(r"(\d{1,3}),(\d{1,3}),(UP|DOWN|LEFT|RIGHT)", re.ASCII)


@dataclass(frozen=True)
class ExportStats:
    maps_kept: int = 0
    maps_dropped: int = 0
    tiles_dropped: int = 0
    blocked_dropped: int = 0
    warps_dropped: int = 0


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _byte(s: str) -> int | None:
    n = int(s)
    return n if 0 <= n <= 255 else None


def _tile(key: object) -> tuple[int, int] | None:
    m = _TILE.fullmatch(key) if isinstance(key, str) else None
    if m is None:
        return None
    x, y = _byte(m.group(1)), _byte(m.group(2))
    return None if x is None or y is None else (x, y)


def _edge(key: object) -> tuple[int, int, int] | None:
    m = _EDGE.fullmatch(key) if isinstance(key, str) else None
    if m is None:
        return None
    x, y = _byte(m.group(1)), _byte(m.group(2))
    return None if x is None or y is None else (x, y, DIRS.index(m.group(3)))


def _dest(v: object) -> tuple[int, int, int] | None:
    if not isinstance(v, list) or len(v) != 3 or not all(_is_int(n) and 0 <= n <= 255 for n in v):
        return None
    return int(v[0]), int(v[1]), int(v[2])


def _edge_out(e: tuple[int, int, int]) -> list:
    return [e[0], e[1], DIRS[e[2]]]


def export_progress(doc: object, game: str) -> tuple[dict, ExportStats]:
    """Return (export, stats). Raises ValueError for an unknown game or a doc without a ``maps`` dict."""
    if not isinstance(game, str) or game not in GAMES:
        raise ValueError(f"unknown game; expected one of {GAMES}")
    if not isinstance(doc, dict) or not isinstance(doc.get("maps"), dict):
        raise ValueError("document is not a dict with a 'maps' dict")
    drop = {"maps": 0, "tiles": 0, "blocked": 0, "warps": 0}
    acc: dict[int, dict] = {}
    for key, entry in doc["maps"].items():
        mid = _byte(key) if isinstance(key, str) and _MAP_ID.fullmatch(key) else None
        if mid is None or not isinstance(entry, dict):
            drop["maps"] += 1
            continue
        a = acc.setdefault(mid, {"tiles": set(), "visits": 0, "blocked": set(), "warps": set()})
        visited = entry.get("visited")
        for k, v in (visited.items() if isinstance(visited, dict) else ()):
            t = _tile(k)
            if t is None or not _is_int(v) or v < 0:
                drop["tiles"] += 1
                continue
            a["tiles"].add(t)
            a["visits"] += int(v)
        blocked = entry.get("blocked")
        for item in (blocked if isinstance(blocked, list) else ()):
            e = _edge(item)
            if e is None:
                drop["blocked"] += 1
            else:
                a["blocked"].add(e)
        warps = entry.get("warps")
        for k, v in (warps.items() if isinstance(warps, dict) else ()):
            e, d = _edge(k), _dest(v)
            if e is None or d is None:
                drop["warps"] += 1
            else:
                a["warps"].add((e, d))
    maps: dict[str, dict] = {}
    totals = {"maps": 0, "walkable_tiles": 0, "blocked_edges": 0, "warps": 0}
    for mid in sorted(acc):
        a = acc[mid]
        walkable = [[x, y] for x, y in sorted(a["tiles"])]
        blocked = [_edge_out(e) for e in sorted(a["blocked"], key=lambda e: (e[0], e[1], DIRS[e[2]]))]
        warps = [{"from": _edge_out(e), "to": list(d)}
                 for e, d in sorted(a["warps"], key=lambda w: (w[0][0], w[0][1], DIRS[w[0][2]], w[1]))]
        stats = {"walkable_tiles": len(walkable), "blocked_edges": len(blocked), "warps": len(warps),
                 "total_visits": a["visits"]}
        maps[str(mid)] = dict(zip(OUTPUT_MAP_FIELDS, (walkable, blocked, warps, stats)))
        totals["maps"] += 1
        totals["walkable_tiles"] += len(walkable)
        totals["blocked_edges"] += len(blocked)
        totals["warps"] += len(warps)
    out = {"schema_version": SCHEMA_VERSION, "kind": KIND, "game": GAMES[GAMES.index(game)],
           "maps": maps, "totals": totals}
    return out, ExportStats(totals["maps"], drop["maps"], drop["tiles"], drop["blocked"], drop["warps"])
