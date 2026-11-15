"""ledges: classify a recorded wall edge (a ``blocked`` entry) by whether a ledge explains it.

``MapMemory.learn`` records a ledge hop as ``jumps["x0,y0,B"] = [x1, y1]`` and then appends the
back-edge ``f"{x1},{y1},{opposite(B)}"`` to ``blocked`` so the agent stops trying to climb back up.
A baseline ``blocked`` edge that a candidate stood on both ends of is only a SUSPECT wall - these
classifiers split the ledge-explained suspects from the unexplained ones.
"""
from __future__ import annotations

from pokeagent.brain.common import DIRS

_OPPOSITE = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}


def opposite(button: str) -> str:
    """The direction that would walk back the way ``button`` moved; unknown inputs pass through."""
    return _OPPOSITE.get(button, button)


def parse_edge(edge: str) -> tuple[int, int, str]:
    """``"x,y,BUTTON"`` -> ``(x, y, button)``; ``ValueError`` on a malformed edge."""
    parts = str(edge).split(",")
    if len(parts) != 3:
        raise ValueError(f"malformed edge: {edge!r}")
    button = parts[2]
    if button not in DIRS:
        raise ValueError(f"malformed edge: {edge!r}")
    return int(parts[0]), int(parts[1]), button


def _jumps(map_doc: dict):
    """Well-formed ``(x0, y0, button, x1, y1)`` tuples from ``map_doc["jumps"]``."""
    for key, dest in (map_doc.get("jumps") or {}).items():
        try:
            x0, y0, b = parse_edge(key)
        except ValueError:
            continue
        if isinstance(dest, (list, tuple)) and len(dest) == 2:
            try:
                yield x0, y0, b, int(dest[0]), int(dest[1])
            except (TypeError, ValueError):
                continue


def classify_wall(map_doc: dict, edge: str) -> str:
    """``ledge_exact`` | ``ledge_row`` (heuristic) | ``plain`` for one ``blocked`` edge.

    ``ledge_exact``: the edge IS the back-edge ``learn()`` wrote for a recorded jump - certain.
    ``ledge_row``: HEURISTIC. The edge points opposite some jump's direction and its source tile
    shares the landing tile's row (UP/DOWN jumps) or column (LEFT/RIGHT jumps). It covers unjumped
    columns of a ledge row, but can be wrong on a map with two ledges in one row.
    ``plain``: anything else, including a malformed edge.
    """
    try:
        x, y, button = parse_edge(edge)
    except ValueError:
        return "plain"
    jumps = list(_jumps(map_doc))
    for _x0, _y0, jb, x1, y1 in jumps:
        if (x, y, button) == (x1, y1, opposite(jb)):
            return "ledge_exact"
    for _x0, _y0, jb, x1, y1 in jumps:
        if opposite(jb) != button:
            continue
        same_line = (y == y1) if jb in ("UP", "DOWN") else (x == x1)
        if same_line:
            return "ledge_row"
    return "plain"
