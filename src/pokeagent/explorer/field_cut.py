"""field_cut: use CUT on a cuttable tree that stands in the route (the Vermilion Gym's tree, stage vermilion_gym_entry).

The route planner (ctx.route_plan, an atlas planner injected by the demo / headless tool; explorer never imports atlas) is asked first
without Cut; only when that finds no way and a party member knows CUT (and the Cascade badge is held) is it asked with ``cut=True``,
where the ROM's cuttable-tree cells are walkable. When that route's next step enters a tree cell the planner records the request here
(``state['want']``: the cell we stand on and the direction of the tree) and presses the direction (a turn toward the tree). The
FieldCut behaviour then drives START -> POKeMON -> the member that knows CUT -> CUT, one press at a time, read off the screen
(party_menu helpers); success is the tree tile gone from the tile in front of us.

Facts: the cuttable tree is overworld tile 0x3D (UsedCut: ``cp $3d`` on wTileInFrontOfPlayer, ROM 0xEF6F; the block swap table is at 0xF100);
CUT is move 15; CASCADEBADGE is wObtainedBadges (0xD356) bit 1. The tile in front of the player on the tile map is (col, row)
UP (8,7), DOWN (8,11), LEFT (6,9), RIGHT (10,9) (the player's bottom-left tile is (8,9)). Caps: PRESS_CAP presses per try, MAX_TRIES
tries per tree, COOLDOWN steps after a failed try.
"""
from __future__ import annotations

from pokeagent.explorer.context import ExplorerContext
from pokeagent.ramstructs import read_party

CUT_MOVE, TREE_TILE, TILESET_ADDR, BADGES_ADDR, CASCADE_BIT = 15, 0x3D, 0xD367, 0xD356, 1
OVERWORLD = 0
AHEAD = {"UP": (8, 7), "DOWN": (8, 11), "LEFT": (6, 9), "RIGHT": (10, 9)}  # tile map (col, row) in front of the player
PRESS_CAP, MAX_TRIES, COOLDOWN, PACE_FRAMES, CALM_FRAMES, AFTER_CUT_STEPS = 60, 3, 400, 8, 6, 40


def state(ctx: ExplorerContext) -> dict:
    return ctx.__dict__.setdefault("field_cut", {"want": None, "seq": None, "cooldown_until": 0, "tries": {}, "cuts": 0})


def cutter_slot(emu) -> int | None:
    """Party slot of the first member that knows CUT, or None."""
    return next((i for i, m in enumerate(read_party(emu)) if CUT_MOVE in m.moves), None)


def can_cut(emu) -> bool:
    return bool(emu.read(BADGES_ADDR) & (1 << CASCADE_BIT)) and cutter_slot(emu) is not None


def tree_ahead(tm: bytes, facing: str, tileset: int) -> bool:
    """The tile in front of the player (read off the tile map, no menu open) is the overworld's cuttable tree."""
    col, row = AHEAD.get(facing, (-1, -1))
    return tileset == OVERWORLD and col >= 0 and tm[row * 20 + col] == TREE_TILE


def offer(ctx: ExplorerContext) -> dict:
    """The planner's view: ``can`` = a route may go through a tree now (a cutter, the badge, no cooldown)."""
    st = state(ctx)
    st["can"] = ctx.step >= st["cooldown_until"] and can_cut(ctx.emu)
    return st


def request(st: dict, pos: tuple, direction: str, tree: tuple) -> None:
    """The planner's route enters ``tree`` (a (map, x, y) cell) by pressing ``direction`` from ``pos``."""
    st["want"] = {"pos": tuple(pos), "dir": direction, "tree": tuple(tree)}


def tries_left(st: dict, tree: tuple) -> bool:
    return st["tries"].get(tree, 0) < MAX_TRIES
