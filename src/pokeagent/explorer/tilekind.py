"""classify: which legend kind one tile is, by the precedence in the World Legend directive.

``memory_map`` is the per-map dict (``maps[str(m)]``: visited, blocked, warps, jumps, interactions,
npcs, encounters). ``tile_types``/``grass_ids`` are the global learned tables and ``block`` the tile's
four block ids - ``None`` for Remembers, which has no live tilemap (solid/grass then come only from
what memory itself recorded: blocked-edge targets for walls, interaction targets for objects).
``npcs_here`` is a set of ``(x, y)`` positions; ``trainers`` maps ``(x, y)`` -> the npc entry
(``trainer_tiles`` builds it). ``you`` is never returned: the renderer overlays the player itself.
"""
from __future__ import annotations

from pokeagent.explorer.items import is_item_ball

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def _block_key(block) -> str:
    return ",".join(f"{b:02X}" for b in block)


def _entry(table: dict, tileset: int, block):
    if block is None:
        return None
    return (table or {}).get(str(tileset), {}).get(_block_key(block))


def _solid(tile_types: dict, tileset: int, block, strict: bool = True) -> bool:
    """The block was learned solid. strict (Remembers, same rule as MapMemory.known_solid): solid>=3 and never
    walkable. Not strict (the Sees view, its original rule): solid outweighs walkable."""
    e = _entry(tile_types, tileset, block)
    if not e:
        return False
    if strict:
        return e.get("solid", 0) >= 3 and e.get("walkable", 0) == 0
    return e.get("solid", 0) > e.get("walkable", 0)


def _walkable(tile_types: dict, tileset: int, block) -> bool:
    e = _entry(tile_types, tileset, block)
    return bool(e) and e.get("walkable", 0) > e.get("solid", 0)


def is_grass(grass_ids: dict, tileset: int, block) -> bool:
    return block is not None and _block_key(block) in (grass_ids or {}).get(str(tileset), {})


def _prefix_hit(keys, x: int, y: int) -> bool:
    """Some ``x,y,DIR`` key exists for this tile (the trailing comma keeps (1,2) off (1,23))."""
    p = f"{x},{y},"
    return any(k.startswith(p) for k in keys)


def _with_text(inter: dict, x: int, y: int) -> bool:
    """A recorded interaction WITH text happened standing on (x,y): the 'i' talk spot."""
    return _prefix_hit((k for k, e in inter.items() if e.get("text")), x, y)


def _aimed_at(inter: dict, x: int, y: int) -> bool:
    """A recorded interaction WITH text was aimed AT (x,y): the player stood one step back facing it.
    That makes the tile an 'o' object (sign, PC, item ball) rather than a bare wall."""
    for key, e in inter.items():
        if not e.get("text"):
            continue
        parts = key.split(",")
        if len(parts) != 3:
            continue
        px, py, facing = parts
        dx, dy = DIRS.get(facing, (0, 0))
        if int(px) + dx == x and int(py) + dy == y:
            return True
    return False


def _blocked_target(d: dict, x: int, y: int) -> bool:
    """(x,y) is the far side of a confirmed blocked edge: memory's own record of 'cannot enter'."""
    for k in d.get("blocked", []):
        parts = k.split(",")
        if len(parts) != 3:
            continue
        bx, by, bd = parts
        dx, dy = DIRS.get(bd, (0, 0))
        if int(bx) + dx == x and int(by) + dy == y:
            return True
    return False


def ledge_dir(memory_map: dict, x: int, y: int) -> str | None:
    """The jump direction whose ledge tile is (x,y): one step from the jump's start toward its landing.
    The ledge glyph is drawn on that tile - where the ledge shows on screen."""
    for key in (memory_map or {}).get("jumps", {}):
        parts = key.split(",")
        if len(parts) != 3:
            continue
        sx, sy, direction = parts
        dx, dy = DIRS.get(direction, (0, 0))
        if int(sx) + dx == x and int(sy) + dy == y:
            return direction
    return None


def trainer_tiles(memory_map: dict) -> dict:
    """``{(x, y): npc entry}`` for NPCs marked ``trainer``, keyed by last-seen tile."""
    return {tuple(e["last"]): e for e in (memory_map or {}).get("npcs", {}).values()
            if e.get("trainer") and e.get("last")}


def item_tiles(memory_map: dict) -> dict:
    """``{(x, y): npc entry}`` for NPCs that are item balls (pic 61, never seen moving)."""
    return {tuple(e["last"]): e for e in (memory_map or {}).get("npcs", {}).values()
            if is_item_ball(e) and e.get("last")}


def classify(memory_map: dict, tile_types: dict, grass_ids: dict, tileset: int,
             x: int, y: int, block, npcs_here, trainers, items=None, strict: bool = True) -> str:
    """The legend kind for tile (x,y), by precedence: trainer > item > npc > warp > ledge > object > wall >
    encounter > grass > interaction > walkable > unknown. ``items`` is a set/dict of item-ball tiles
    (``item_tiles`` for Remembers, live sprite positions for Sees); None means none are known."""
    p = (x, y)
    trainer = trainers.get(p) if hasattr(trainers, "get") else None
    if trainer is not None:
        return "trainer_beaten" if trainer.get("beaten") else "trainer"
    if items and p in items:
        return "item"
    if p in (npcs_here or ()):
        return "npc"
    d = memory_map or {}
    if _prefix_hit(d.get("warps", {}), x, y):
        return "warp"
    if ledge_dir(d, x, y) is not None:
        return "ledge"
    visited = f"{x},{y}" in d.get("visited", {})
    inter = d.get("interactions", {})
    if _aimed_at(inter, x, y) and not visited and not _walkable(tile_types, tileset, block):
        return "object"
    if not visited and (_solid(tile_types, tileset, block, strict) or _blocked_target(d, x, y)):
        return "wall"
    if f"{x},{y}" in d.get("encounters", {}):
        return "encounter"
    if is_grass(grass_ids, tileset, block):
        return "grass"
    if _with_text(inter, x, y):
        return "interaction"
    if visited or _walkable(tile_types, tileset, block):
        return "walkable"
    return "unknown"
