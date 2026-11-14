"""The Red label source on a fabricated sprite table, and the game registry."""
from __future__ import annotations

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.vision.source_red import RedSource
from pokeagent.vision.sources import SOURCES, get_source

PLAYER = (1, 0, 5, 6, 0)          # (pic, img idx, map x, map y, move) for slot 0


def red_mem(*slots, battle=0, tileset=4, map_id=5, px=5, py=6, lcdc=0, scx=0, scy=0, tile=7):
    mem = {0xD35E: map_id, 0xD361: py, 0xD362: px, 0xD057: battle, 0xD367: tileset,
           0xFF40: lcdc, 0xFF42: scy, 0xFF43: scx}
    for i, (pic, img, nx, ny, move) in enumerate(slots):
        mem[0xC100 + 16 * i], mem[0xC100 + 16 * i + 2] = pic, img
        mem[0xC200 + 16 * i + 4], mem[0xC200 + 16 * i + 5], mem[0xC200 + 16 * i + 6] = ny + 4, nx + 4, move
    mem.update({0x9800 + i: tile for i in range(1024)})
    return FakeEmulator(mem)


def test_npc_box_formula_labels_and_player():
    labels = RedSource().read(red_mem(PLAYER, (13, 0, 6, 7, 0xFE)))
    npc = next(s for s in labels.sprites if s.ident == "slot1")
    assert (npc.x, npc.y, npc.w, npc.h) == (80, 76, 16, 16)   # one map tile right and down of the player
    assert npc.label == 13 and npc.coarse == "npc" and npc.move == 0xFE and npc.pos == (6, 7)
    me = next(s for s in labels.sprites if s.ident == "slot0")
    assert me.coarse == "player" and (me.x, me.y) == (64, 60) and me.pos == (5, 6)
    assert labels.area == "map-5" and labels.bank == 4 and labels.player == (5, 6) and labels.cell == "1,1"


def test_ball_is_item_hidden_and_empty_slots_dropped():
    labels = RedSource().read(red_mem(PLAYER, (61, 0, 6, 6, 0xFF), (9, 0xFF, 7, 6, 0), (0, 0, 8, 6, 0)))
    by_ident = {s.ident: s for s in labels.sprites}
    assert by_ident["slot1"].coarse == "item" and "slot2" not in by_ident and "slot3" not in by_ident


def test_off_screen_boxes_dropped_partial_kept():
    labels = RedSource().read(red_mem(PLAYER, (13, 0, 11, 6, 0), (14, 0, 5, 2, 0)))
    by_ident = {s.ident: s for s in labels.sprites}
    assert "slot1" not in by_ident                      # x = 64 + 6*16 = 160, entirely off screen
    assert by_ident["slot2"].y == -4                    # partially off screen is kept


def test_skips_in_battle_and_when_no_slot_read_is_sane():
    assert RedSource().read(red_mem(PLAYER, battle=1)).skip
    assert RedSource().read(red_mem()).skip             # every slot empty: not the overworld


def test_tiles_skip_sprite_boxes_and_honour_the_map_select_bit():
    emu = red_mem(PLAYER, (13, 0, 5, 6, 0))
    labels = RedSource().read(emu)
    assert labels.tiles and all(c.label == 7 for c in labels.tiles)
    boxes = [(s.x, s.y) for s in labels.sprites]
    for c in labels.tiles:                              # no emitted tile overlaps a sprite box
        assert not any(c.x < bx + 16 and bx < c.x + 8 and c.y < by + 16 and by < c.y + 8
                       for bx, by in boxes)
    emu2 = red_mem(PLAYER)
    emu2.memory.update({0x9C00 + i: 9 for i in range(1024)})
    emu2.set(0xFF40, 0x08)                              # LCDC bit 3: map at 0x9C00
    assert {c.label for c in RedSource().read(emu2).tiles} == {9}
    assert {c.label for c in RedSource().read(emu).tiles} == {7}


def test_registry_holds_only_pokemon_red_and_errors_clearly():
    assert set(SOURCES) == {"pokemon-red"}
    assert get_source("pokemon-red") is SOURCES["pokemon-red"]
    with pytest.raises(ValueError, match="mario-land"):
        get_source("mario-land")
    with pytest.raises(ValueError):
        get_source("not-a-game")
