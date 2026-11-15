"""door_exit: press out of an unlearned door mat before patrolling.

The map memory only learns a warp by taking it. A run that starts INSIDE a house (a saved state: 88_2_7 in Bill's house) has no warp
learned and the screen tile beyond the mat reads as solid, so the explore pick marks that side 'blocked' without ever pressing it and
the agent patrolled the house for 2,800 steps after the S.S. Ticket (seen 2026-11-15). The game's own warp table (wWarpEntries) names
the door tiles; two real presses out of an edge tile settle it (a failed press is counted in ``fails`` and never retried)."""
from __future__ import annotations

from pokeagent.ramworld import read_map_header

MAX_TRIES = 2  # the map memory records a warp on its SECOND sighting; the first exit may bounce straight back in (new-map burst)


def door_press(ctx, m: int, x: int, y: int) -> tuple[str, str] | None:
    """('DOWN'|'UP'|'LEFT'|'RIGHT', why) when (x, y) is a header warp tile on the map edge and that outward press was never tried."""
    try:
        h = read_map_header(ctx.emu)
        w, ht = h.width * 2, h.height * 2
    except Exception:  # noqa: BLE001  fake / unreadable header: no door knowledge
        return None
    d = ctx.mem.m(m)
    for wp in h.warps:
        if (wp.x, wp.y) != (x, y):
            continue
        for name, edge in (("DOWN", y == ht - 1), ("UP", y == 0), ("LEFT", x == 0), ("RIGHT", x == w - 1)):
            key = f"{x},{y},{name}"
            if edge and not d.get("fails", {}).get(key) and d.get("door_tried", {}).get(key, 0) < MAX_TRIES:
                tried = d.setdefault("door_tried", {})
                tried[key] = tried.get(key, 0) + 1
                return name, f"standing on the door tile ({x},{y}) with nothing left to explore: pressing {name} to leave"
    return None
