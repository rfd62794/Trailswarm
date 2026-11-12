"""Story blockers the grind episode must not route through.

An interaction typed ``blocker`` (interaction_types: "the same text came back and the player was pushed back" - the
drunk old man north of Viridian until Oak's parcel is delivered) records the goal stage it was met at. While the run
is still at that stage the NPC's tile is a wall for routing; once the stage moves on the entry is no longer active
(interaction_policy retries it once). A grind episode that routed to Route 2's grass walked into him over and over
(334+ steps, 2026-11-11) and starved the parcel goal; ``blocked_tiles`` feeds the episode's start gate, its
route and its end check.
"""
from __future__ import annotations

from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.interaction_types import BLOCKER
from pokeagent.explorer.world import DIRS


def blocked_tiles(ctx) -> frozenset:
    """{(map, x, y)}: the tile in front of every blocker interaction recorded at the current goal stage."""
    stage = goal_stage(ctx.goals())
    out = set()
    for mid, d in (ctx.mem.data.get("maps") or {}).items():
        for key, e in (d.get("interactions") or {}).items():
            if (e or {}).get("type") != BLOCKER or e.get("goal") != stage:
                continue
            try:
                x, y, name = key.split(",")
                dx, dy = DIRS[name]
                out.add((int(mid), int(x) + dx, int(y) + dy))
            except (ValueError, KeyError):
                continue
    return frozenset(out)


def reachable(maps: dict, pos: tuple, map_id: int, blocked) -> bool:
    """Is ``map_id`` reachable from ``pos`` over the learned graph with ``blocked`` tiles as walls?"""
    from pokeagent.explorer.world import WorldGraph
    if pos[0] == map_id:
        return True
    g = WorldGraph(maps)
    g.blocked_now = frozenset(blocked)
    return g.path(tuple(pos), lambda n: n[0] == map_id) is not None
