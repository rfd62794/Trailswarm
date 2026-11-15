"""Semantic vision labels: one vocabulary that means the same thing in every tileset.

A raw tile id only means something inside its tileset (44 is grass in one, a wall in
another), so a model scored on ``tile:<id>@<bank>`` cannot generalise to held-out maps.
The semantic class is derived from game data instead: the collision list, the tileset
header's grass/counter bytes, and the ledge table say what a tile DOES, not what it is.

Not in the vocabulary - the repo reads no tile-level data for these today: water,
warp/door tiles, signs, trees, buildings. Water and trees are non-walkable and land in
``solid``; doors and warps are in the collision list and land in ``walkable``. A later
directive can add them once the data exists.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pokeagent.legs.grid import LEDGES

SEMANTIC = ("walkable", "solid", "grass", "counter", "ledge", "npc", "item", "player", "other")
LEDGE_FRONT = frozenset(t for _f, _s, t in LEDGES)
BALL_PIC = 61


@dataclass(frozen=True)
class TilesetFacts:
    """The tileset header facts a cell's class is decided from."""

    tileset: int
    walkable: frozenset      # collision-list tile ids
    grass: int               # grass tile id, 0xFF = none
    counters: frozenset      # counter tile ids with 0xFF removed


def cell_class(tile: int, facts: TilesetFacts) -> str:
    """The semantic class of a 2x2-tile cell whose stepping tile is ``tile``."""
    if facts.tileset == 0 and tile in LEDGE_FRONT and tile not in facts.walkable:
        return "ledge"
    if tile == facts.grass and facts.grass != 0xFF and tile in facts.walkable:
        return "grass"
    if tile in facts.counters:
        return "counter"
    if tile in facts.walkable:
        return "walkable"
    return "solid"


def tile_table(blockset: np.ndarray, facts: TilesetFacts) -> tuple[dict[int, str], int]:
    """Tile id -> semantic class for one tileset, plus the count of ambiguous ids.

    The player steps in 2x2-tile cells; the game tests only the cell's bottom-left
    tile against the collision list, so a tile id never used as a stepping tile (a
    wall top, a floor edge) must not be judged by the list. Every cell's class is
    instead credited to all four tile ids the cell covers, and a tile id takes its
    most credited class (a tie goes to the class earlier in ``SEMANTIC``). Ids
    credited to more than one class are counted in the second return value; ids
    credited nowhere are absent from the table and read as ``other`` downstream.
    """
    votes: dict[int, dict[str, int]] = {}
    for block in np.asarray(blockset).reshape(-1, 4, 4):
        for cy in (0, 1):
            for cx in (0, 1):
                cls = cell_class(int(block[2 * cy + 1, 2 * cx]), facts)
                for tid in np.asarray(block[2 * cy:2 * cy + 2, 2 * cx:2 * cx + 2]).flat:
                    v = votes.setdefault(int(tid), {})
                    v[cls] = v.get(cls, 0) + 1
    table, ambiguous = {}, 0
    for tid, counts in votes.items():
        if len(counts) > 1:
            ambiguous += 1
        table[tid] = min(counts, key=lambda c: (-counts[c], SEMANTIC.index(c)))
    return table, ambiguous


def sprite_class(label: int, coarse: str) -> str:
    """The semantic class of a sprite row: the pick-up ball is an item, whatever its coarse."""
    if label == BALL_PIC:
        return "item"
    return coarse if coarse in ("player", "npc", "item") else "other"


def row_class(row: dict, tables: dict[int, dict[int, str]]) -> str:
    """One samples.jsonl row's semantic class; anything unmappable is ``other``."""
    if row["kind"] == "sprite":
        return sprite_class(row["label"], row.get("coarse", ""))
    if row["kind"] == "tile":
        table = tables.get(row["bank"]) if row["bank"] is not None else None
        return table.get(row["label"], "other") if table else "other"
    return "other"
