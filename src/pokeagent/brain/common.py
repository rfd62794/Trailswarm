"""Shared helpers for the brain query library: tile-key parsing and the set of tiles memory knows."""
from __future__ import annotations

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def parse_tile(key) -> tuple[int, int] | None:
    """First two components of a 'x,y[,DIR]' key as ints, or None."""
    parts = str(key).split(",")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def edge_dir(key) -> str | None:
    """The trailing DIR/FACING of an 'x,y,DIR' key, or None."""
    parts = str(key).split(",")
    return parts[2] if len(parts) == 3 else None


def _add(tiles: set, key) -> tuple[int, int] | None:
    p = parse_tile(key)
    if p is not None:
        tiles.add(p)
    return p


def _edge(tiles: set, key) -> None:
    """'x,y,DIR': add the source tile and the tile one step ahead (a wall/ledge target is known too)."""
    p = _add(tiles, key)
    if p is None:
        return
    dx, dy = DIRS.get(edge_dir(key) or "", (0, 0))
    tiles.add((p[0] + dx, p[1] + dy))


def known_tiles(d: dict) -> set[tuple[int, int]]:
    """Every (x, y) the per-map memory dict has any fact about."""
    tiles: set[tuple[int, int]] = set()
    for sect in ("visited", "encounters", "outcomes", "tile_overrides"):
        for k in (d.get(sect) or {}):
            _add(tiles, k)
    for sect in ("fails", "blocked"):
        for k in (d.get(sect) or {}):
            _edge(tiles, k)
    for sect in ("warps", "warp_cand", "interactions"):
        for k in (d.get(sect) or {}):
            _add(tiles, k)
    for k, v in (d.get("jumps") or {}).items():
        p = _add(tiles, k)
        if p is not None:
            dx, dy = DIRS.get(edge_dir(k) or "", (0, 0))
            tiles.add((p[0] + dx, p[1] + dy))  # the ledge tile the press hops over
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    tiles.add((int(v[0]), int(v[1])))  # the landing tile
                except (TypeError, ValueError):
                    pass
    for n in (d.get("npcs") or {}).values():
        last = n.get("last")
        if isinstance(last, (list, tuple)) and len(last) == 2:
            try:
                tiles.add((int(last[0]), int(last[1])))
            except (TypeError, ValueError):
                pass
        for pk in (n.get("positions") or {}):
            _add(tiles, pk)
    for dm in (d.get("demos") or []):
        at = dm.get("at") if isinstance(dm, dict) else None
        if isinstance(at, (list, tuple)) and len(at) == 2:
            try:
                tiles.add((int(at[0]), int(at[1])))
            except (TypeError, ValueError):
                pass
    return tiles


def npc_tiles(d: dict) -> set[tuple[int, int]]:
    """Last-seen positions of recorded NPCs (what classify treats as 'npc' candidates)."""
    out = set()
    for n in (d.get("npcs") or {}).values():
        last = n.get("last")
        if isinstance(last, (list, tuple)) and len(last) == 2:
            try:
                out.add((int(last[0]), int(last[1])))
            except (TypeError, ValueError):
                pass
    return out


def mid_key(mid: str):
    """Sort maps.json keys numerically when possible ('9' before '12')."""
    try:
        return (0, int(mid))
    except (TypeError, ValueError):
        return (1, str(mid))
