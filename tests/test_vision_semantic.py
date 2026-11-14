"""semantic.py: the vocabulary, the five-step cell precedence, tile-table crediting, row mapping."""
from __future__ import annotations

import numpy as np

from pokeagent.vision_model.semantic import (BALL_PIC, SEMANTIC, TilesetFacts,
                                           cell_class, row_class, sprite_class,
                                           tile_table)


def facts(walkable=(), grass=0xFF, counters=(), tileset=3):
    return TilesetFacts(tileset, frozenset(walkable), grass, frozenset(counters))


def test_cell_class_precedence():
    f = facts(walkable={0x10, 0x20}, grass=0x20, counters={0x30})
    assert cell_class(0x20, f) == "grass"       # grass beats walkable
    assert cell_class(0x30, f) == "counter"     # counter ids are not in the collision list
    assert cell_class(0x10, f) == "walkable"
    assert cell_class(0x99, f) == "solid"


def test_ledge_only_on_tileset_zero_and_only_when_not_walkable():
    assert cell_class(0x37, facts(tileset=0)) == "ledge"
    assert cell_class(0x37, facts(tileset=1)) == "solid"          # same id, another tileset
    assert cell_class(0x37, facts(walkable={0x37}, tileset=0)) == "walkable"
    assert cell_class(0x36, facts(tileset=0)) == "ledge"          # every ledge-front id counts


def test_grass_0xff_means_none_and_counter_needs_the_id():
    f = facts(walkable={0xFF}, grass=0xFF)
    assert cell_class(0xFF, f) == "walkable"    # grass byte 0xFF: no grass on this tileset
    assert cell_class(0x20, facts(counters={0x20})) == "counter"


def test_tile_table_credits_stepping_and_covered_tiles():
    """A wall top never stepped on stays solid; a floor edge inside a walkable cell walks."""
    F, W, E, T = 0x10, 0x99, 0x20, 0x30
    block = np.array([[E, E, E, E],
                      [F, E, F, E],
                      [E, E, T, T],
                      [F, E, W, T]], np.uint8)
    table, ambiguous = tile_table(block[None], facts(walkable={F}))
    assert table[F] == "walkable" and table[W] == "solid"
    assert table[E] == "walkable"     # only ever a non-stepping tile of walkable cells
    assert table[T] == "solid"        # only ever a non-stepping tile of the solid cell
    assert ambiguous == 0


def test_tile_table_tie_goes_to_earlier_semantic():
    F, S, X, A = 0x10, 0x99, 0x20, 0x30
    block = np.array([[X, A, A, A],
                      [F, A, A, A],
                      [X, A, A, A],
                      [S, A, S, A]], np.uint8)
    table, ambiguous = tile_table(block[None], facts(walkable={F}))
    # X: one walkable credit (cell 0,0) vs one solid credit (cell 1,0) -> tie -> walkable
    assert table[X] == "walkable"
    assert ambiguous == 2             # X and A were each credited to two classes


def test_sprite_class():
    assert sprite_class(BALL_PIC, "npc") == "item"      # picture id 61 wins over coarse
    assert sprite_class(1, "player") == "player"
    assert sprite_class(13, "npc") == "npc"
    assert sprite_class(13, "item") == "item"
    assert sprite_class(40, "enemy") == "other"
    assert sprite_class(40, "other") == "other"


def test_row_class():
    tables = {2: {7: "walkable", 9: "solid"}}
    tile = {"kind": "tile", "bank": 2, "label": 7}
    assert row_class(tile, tables) == "walkable"
    assert row_class({**tile, "label": 5}, tables) == "other"     # id never credited
    assert row_class({**tile, "bank": 99}, tables) == "other"     # tileset with no table
    assert row_class({**tile, "bank": None}, tables) == "other"
    assert row_class({"kind": "sprite", "label": 13, "coarse": "npc"}, tables) == "npc"
    assert row_class({"kind": "sprite", "label": 1, "coarse": "player"}, tables) == "player"
    assert row_class({"kind": "sprite", "label": BALL_PIC, "coarse": "npc"}, tables) == "item"
    assert row_class({"kind": "sprite", "label": 40, "coarse": "enemy"}, tables) == "other"
