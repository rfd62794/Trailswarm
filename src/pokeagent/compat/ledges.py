"""Wall classifier: is a blocked edge a ledge (one-way terrain) or a plain wall?

Implemented here because ``brain/ledges.py`` (Brain_Compare_And_Run_Reports_Directive, Draft) is not on main.
Pure functions over one map document (``doc["maps"][id]``); no ROM access.
"""
from __future__ import annotations

_OPP = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
VERTICAL = ("UP", "DOWN")


def opposite(button: str) -> str:
    return _OPP[button]


def parse_edge(edge: str) -> tuple[int, int, str]:
    """``"x,y,BUTTON"`` -> (x, y, BUTTON); ValueError when malformed."""
    parts = str(edge).split(",")
    if len(parts) != 3 or parts[2] not in _OPP:
        raise ValueError(f"malformed edge: {edge!r}")
    return int(parts[0]), int(parts[1]), parts[2]


def classify_wall(map_doc: dict, edge: str) -> str:
    """``ledge_exact`` | ``ledge_row`` (HEURISTIC) | ``plain``."""
    x, y, b = parse_edge(edge)
    for key, land in (map_doc.get("jumps") or {}).items():
        try:
            _x0, _y0, jb = parse_edge(key)
            lx, ly = int(land[0]), int(land[1])
        except (ValueError, TypeError, IndexError):
            continue
        if edge == f"{lx},{ly},{opposite(jb)}":
            return "ledge_exact"
    for key, land in (map_doc.get("jumps") or {}).items():
        try:
            _x0, _y0, jb = parse_edge(key)
            lx, ly = int(land[0]), int(land[1])
        except (ValueError, TypeError, IndexError):
            continue
        if b == opposite(jb) and ((y == ly) if jb in VERTICAL else (x == lx)):
            return "ledge_row"
    return "plain"
