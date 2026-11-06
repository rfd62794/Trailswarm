"""tile_facts: every fact the model holds about one tile, plus the journal edits touching it."""
from __future__ import annotations

from pokeagent.brain.common import DIRS, edge_dir, npc_tiles, parse_tile
from pokeagent.explorer import tilekind


def _at(d: dict, sect: str, x: int, y: int) -> dict:
    """Entries of ``d[sect]`` whose key's tile part is (x, y)."""
    return {k: v for k, v in (d.get(sect) or {}).items() if parse_tile(k) == (x, y)}


def _blocked_edges(d: dict, x: int, y: int) -> tuple[list, list]:
    """Confirmed blocked edges AT (x,y) ['UP', ...] and edges whose target IS (x,y)."""
    frm, into = [], []
    for k in d.get("blocked") or []:
        p = parse_tile(k)
        direction = edge_dir(k)
        if p is None or direction is None:
            continue
        if p == (x, y):
            frm.append(direction)
        else:
            dx, dy = DIRS.get(direction, (0, 0))
            if (p[0] + dx, p[1] + dy) == (x, y):
                into.append({"from": f"{p[0]},{p[1]}", "dir": direction})
    return sorted(frm), sorted(into, key=lambda e: (e["from"], e["dir"]))


def _jumps(d: dict, x: int, y: int) -> tuple[dict, list]:
    """Ledge jumps STARTING at (x,y) {'x,y,DIR': [lx,ly]} and jumps whose ledge tile is (x,y)."""
    jumps = _at(d, "jumps", x, y)
    into = []
    for k in (d.get("jumps") or {}):
        p = parse_tile(k)
        direction = edge_dir(k)
        if p is None or direction is None or p == (x, y):
            continue
        dx, dy = DIRS.get(direction, (0, 0))
        if (p[0] + dx, p[1] + dy) == (x, y):
            into.append({"from": [p[0], p[1]], "dir": direction})
    return jumps, into


def _aimed_at(d: dict, x: int, y: int) -> list:
    """Interactions aimed AT (x,y): the player stood one step back facing this tile."""
    out = []
    for k, e in (d.get("interactions") or {}).items():
        p = parse_tile(k)
        direction = edge_dir(k)
        if p is None or direction is None or not (e or {}).get("text"):
            continue
        dx, dy = DIRS.get(direction, (0, 0))
        if (p[0] + dx, p[1] + dy) == (x, y):
            out.append({"spot": k, "text": (e or {}).get("text", "")[:80]})
    return out


def _npc_facts(d: dict, x: int, y: int) -> list:
    out = []
    for nid, n in (d.get("npcs") or {}).items():
        if n.get("last") == [x, y]:
            out.append({"id": nid, "pic": n.get("pic"), "slot": n.get("slot"),
                        "trainer": bool(n.get("trainer")), "beaten": bool(n.get("beaten")),
                        "talked": n.get("talked", 0), "moves": bool(n.get("moves")),
                        "text": (n.get("text") or "")[:80], "last": n.get("last")})
    return out


def _edit_touches(e: dict, mid: str, x: int, y: int, by_id: dict, depth: int = 0) -> bool:
    """Does journal edit ``e`` touch tile (x,y) on map ``mid`` (undo resolves to its target)?"""
    if depth > 4 or str(e.get("map")) != str(mid):
        return False
    if e.get("op") == "undo":
        t = by_id.get(e.get("value"))
        return t is not None and _edit_touches(t, mid, x, y, by_id, depth + 1)
    if parse_tile(e.get("key")) == (x, y):
        return True
    v = e.get("value")
    if e.get("op") == "warp_add" and isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return int(v[0]) == int(mid) and (int(v[1]), int(v[2])) == (x, y)
        except (TypeError, ValueError):
            return False
    if e.get("op") == "jump_add" and isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return (int(v[0]), int(v[1])) == (x, y)
        except (TypeError, ValueError):
            return False
    return False


def tile_facts(data: dict, map_id, x: int, y: int, edits=None) -> dict:
    """Everything the model believes about tile (x,y) on ``map_id``, journal edits included."""
    mid = str(map_id)
    d = (data.get("maps") or {}).get(mid) or {}
    xy = f"{x},{y}"
    blocked_from, blocked_into = _blocked_edges(d, x, y)
    jumps, ledge_into = _jumps(d, x, y)
    out = {
        "map": mid, "x": x, "y": y,
        "kind": tilekind.classify(d, data.get("tile_types") or {}, data.get("grass_ids") or {},
                                  0, x, y, None, npc_tiles(d), tilekind.trainer_tiles(d)),
        "tile_kind_override": (d.get("tile_overrides") or {}).get(xy),
        "visited": (d.get("visited") or {}).get(xy, 0),
        "blocked_from": blocked_from,
        "blocked_into": blocked_into,
        "warps": _at(d, "warps", x, y),
        "warp_cand": _at(d, "warp_cand", x, y),
        "warp_taken": _at(d, "warp_taken", x, y),
        "warp_disproof": _at(d, "warp_disproof", x, y),
        "jumps": jumps,
        "ledge_into": ledge_into,
        "interactions": _at(d, "interactions", x, y),
        "interactions_aimed": _aimed_at(d, x, y),
        "npcs": _npc_facts(d, x, y),
        "encounters": (d.get("encounters") or {}).get(xy, 0),
        "fails": _at(d, "fails", x, y),
        "outcomes": _at(d, "outcomes", x, y),
    }
    records = [e for e in (edits or []) if isinstance(e, dict)]
    if records:
        by_id = {e.get("id"): e for e in records if e.get("id") is not None}
        out["edits"] = [e for e in records if _edit_touches(e, mid, x, y, by_id)]
    return out
