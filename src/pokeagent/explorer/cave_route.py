"""cave_route: lead the cave walk toward the next ladder, using the warps the ROM's map header lists.

Mt Moon's floors are a maze the learned graph only knows where we have walked. The header (pokeagent.atlas.rom_maps) says
where every ladder is, so the agent can walk to the KNOWN tile closest to the stage's ladder and let frontier exploration
take it from there, instead of wandering the least-visited tiles for thousands of presses. A tile already stood on
``MAX_PULL_VISITS`` times no longer pulls (a dead end must not trap the agent in a pull/explore loop).
"""
from __future__ import annotations

from pokeagent.explorer.world import WorldGraph

MAX_PULL_VISITS = 3
MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F, ROUTE4 = 0x3B, 0x3C, 0x3D, 0x0F
# (stage, current floor) -> the map the warp we want leads to. The way out is B2F -> B1F -> its east exit (27,3) to Route 4
# (ROM header: B1F has the only other warp to the outside than 1F's west mouth). ``ctx.ladders`` is built by
# pokeagent.atlas.ladders.rom_ladders (the explorer package may not import the atlas).
LADDER_DEST = {("to_mt_moon", MT_MOON_1F): MT_MOON_B1F, ("mt_moon_b1f", MT_MOON_1F): MT_MOON_B1F,
               ("mt_moon_b2f", MT_MOON_B1F): MT_MOON_B2F, ("through_mt_moon", MT_MOON_B1F): ROUTE4,
               ("through_mt_moon", MT_MOON_B2F): MT_MOON_B1F, ("through_mt_moon", MT_MOON_1F): MT_MOON_B1F}


def ladder_step(g: WorldGraph, maps: dict, stage: str, pos: tuple, ladders=None) -> tuple[str, str] | None:
    """The next press toward the known tile nearest the stage's ladder; None when there is nothing to gain (already
    there, no ladder wanted on this floor, or the closest tile was tried ``MAX_PULL_VISITS`` times)."""
    dest = LADDER_DEST.get((stage, pos[0]))
    targets = ladders(pos[0], dest) if ladders is not None and dest is not None else []
    if not targets:
        return None
    visited = maps.get(str(pos[0]), {}).get("visited", {})

    def gap(t: tuple) -> int:
        return min(abs(t[0] - tx) + abs(t[1] - ty) for tx, ty in targets)

    here = gap((pos[1], pos[2]))
    cands = []
    for key, n in visited.items():
        x, y = (int(v) for v in key.split(","))
        if gap((x, y)) < here and n < MAX_PULL_VISITS:
            cands.append((gap((x, y)), x, y))
    for _d, x, y in sorted(cands)[:6]:  # each try is a BFS
        p = g.path(pos, lambda n, x=x, y=y: n == (pos[0], x, y))
        if p:
            return p[0], f"goal {stage}: {len(p)} steps toward the ROM ladder to 0x{dest:02X} (known tile ({x},{y}))"
    return None
