"""Battle item use picks the item BY NAME (bag RAM order + list cursor), blocks a useless item, and caps attempts.

Real case (2026-11-05, Mt Moon 1F): bag ANTIDOTE, TM34, TM12, HP UP, ESCAPE ROPE, RARE CANDY, POTION; the list shows
three rows, POTION was off screen, and the old rule pressed A on ANTIDOTE for 500+ presses.
"""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import item_use as iu
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory

BAG = [0x0B, 0xEA, 0xD4, 0x23, 0x1D, 0x28, 0x14]  # POTION is the 7th row
BAG_RAM = {iu.BAG_COUNT: len(BAG), **{iu.BAG_START + 2 * i + o: v for i, b in enumerate(BAG) for o, v in ((0, b), (1, 1))}}


def make_ctx(tmp_path, mem=None) -> ExplorerContext:
    emu = FakeEmulator({**BAG_RAM, **(mem or {})})
    return ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path,
                           stable_frames=10)


LIST_TOP = [">ANTIDOTE", "x 1", "TM34", "x 1", "TM12", "x 1", "HP UP", "x 1"]
LIST_END = ["RARE CANDY", "x 1", ">POTION", "x 1", "CANCEL"]


def test_bag_index_is_ram_order():
    assert iu.bag_index(FakeEmulator(BAG_RAM), 0x14) == 6
    assert iu.bag_index(FakeEmulator(BAG_RAM), 0x99) is None
    assert iu.bag_index(FakeEmulator(), 0x14) is None


def test_list_scrolls_toward_potion_never_confirms_antidote(tmp_path):
    ctx = make_ctx(tmp_path, {iu.MENU_ITEM: 0, iu.LIST_SCROLL: 0})
    d = iu.item_step(ctx, LIST_TOP, ">ANTIDOTE", 0x14, "POTION", "t")
    assert (d.button, d.rule) == ("DOWN", "item_list_scroll") and ctx.item_attempts == 0
    ctx.emu.set(iu.MENU_ITEM, 2); ctx.emu.set(iu.LIST_SCROLL, 3)  # row 5: still one short
    assert iu.item_step(ctx, LIST_TOP, "", 0x14, "POTION", "t").button == "DOWN"
    ctx.emu.set(iu.LIST_SCROLL, 4)  # row 6 = POTION
    d = iu.item_step(ctx, LIST_END, ">POTION", 0x14, "POTION", "t")
    assert (d.button, d.rule) == ("A", "item_use") and ctx.item_attempts == 1
    ctx.emu.set(iu.LIST_SCROLL, 5)  # overshot onto CANCEL: come back up
    assert iu.item_step(ctx, LIST_END, ">CANCEL", 0x14, "POTION", "t").button == "UP"


def test_battle_menu_navigation_and_party_pick(tmp_path):
    ctx = make_ctx(tmp_path, {iu.PLAYER_MON: 2, iu.MENU_ITEM: 0})
    assert iu.item_step(ctx, ["FIGHT PKMN", ">ITEM RUN"], ">ITEM RUN", 0x14, "POTION", "t").rule == "item_open"
    assert iu.item_step(ctx, [">FIGHT PKMN", "ITEM RUN"], ">FIGHT PKMN", 0x14, "POTION", "t").button == "DOWN"
    assert iu.item_step(ctx, ["FIGHT PKMN", "ITEM >RUN"], ">RUN", 0x14, "POTION", "t").button == "LEFT"
    d = iu.item_step(ctx, ["Use item on which", "POKeMON?"], "", 0x14, "POTION", "t")
    assert (d.button, d.rule) == ("DOWN", "item_party_pick")  # cursor 0, the fighting mon is slot 2
    ctx.emu.set(iu.MENU_ITEM, 2)
    assert iu.item_step(ctx, ["Use item on which", "POKeMON?"], "", 0x14, "POTION", "t").button == "A"
    assert iu.item_step(ctx, ["Wild ZUBAT appeared!"], "", 0x14, "POTION", "t") is None


def test_no_effect_blocks_item_for_the_battle(tmp_path):
    ctx = make_ctx(tmp_path)
    assert not iu.item_is_blocked(ctx, 0x14)
    iu.note_screen(ctx, ["It won have any", "effect."], 0x14)  # the apostrophe glyph is lost in the screen read
    assert iu.item_is_blocked(ctx, 0x14)
    iu.new_battle(ctx)
    assert not iu.item_is_blocked(ctx, 0x14)


def test_attempt_cap_blocks_item(tmp_path):
    ctx = make_ctx(tmp_path, {iu.MENU_ITEM: 2, iu.LIST_SCROLL: 4})
    for _ in range(iu.MAX_ITEM_ATTEMPTS):
        assert not iu.item_is_blocked(ctx, 0x14)
        assert iu.item_step(ctx, LIST_END, ">POTION", 0x14, "POTION", "t").rule == "item_use"
    assert iu.item_is_blocked(ctx, 0x14)


def test_unwanted_list_is_closed_with_b_and_missing_item_closes(tmp_path):
    ctx = make_ctx(tmp_path)
    assert iu.close_unwanted_list(ctx, LIST_TOP).button == "B"
    assert iu.close_unwanted_list(ctx, ["FIGHT PKMN", ">ITEM RUN"]) is None
    assert iu.item_step(ctx, LIST_TOP, "", 0x99, "ELIXIR", "t").button == "B"


# --- cave_escape: the ESCAPE ROPE sequence ---
from pokeagent.explorer.behaviours import cave_escape as ce  # noqa: E402

START_MENU = ["POKeDEX", "POKeMON", ">ITEM", "RED", "SAVE", "OPTION", "EXIT"]


def _hurt(ctx, hp=10, mx=62, bag=None):
    for a, v in {0xD163: 1, 0xD16C: hp >> 8, 0xD16D: hp & 255, 0xD18D: mx >> 8, 0xD18E: mx & 255}.items():
        ctx.emu.set(a, v)
    ctx.emu.set(0xD35E, 0x3B)
    ctx.refresh()


def test_rope_wanted_only_in_cave_hurt_with_no_heal_item(tmp_path):
    ctx = make_ctx(tmp_path)
    _hurt(ctx)
    assert not ce.wants_rope(ctx)           # the bag has a POTION
    ctx.emu.set(iu.BAG_COUNT, 6)            # list now ends before POTION; ESCAPE ROPE (0x1D) is row 4
    ctx.refresh()
    assert ce.wants_rope(ctx)
    ctx.emu.set(0xD35E, 0x0E); ctx.refresh()
    assert not ce.wants_rope(ctx)           # outside the cave
    _hurt(ctx, hp=40)
    assert not ce.wants_rope(ctx)           # not critical


def test_rope_sequence_reads_the_screen(tmp_path):
    ctx = make_ctx(tmp_path, {iu.MENU_ITEM: 0, iu.LIST_SCROLL: 0})
    assert ce.rope_press(ctx, []).button == "START"
    assert ce.rope_press(ctx, [">POKeDEX", "POKeMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT"]).button == "DOWN"
    assert ce.rope_press(ctx, START_MENU).button == "A"
    d = ce.rope_press(ctx, LIST_TOP)         # ESCAPE ROPE is bag row 4, cursor at row 0
    assert (d.button, d.rule) == ("DOWN", "item_list_scroll")
    ctx.emu.set(iu.MENU_ITEM, 2); ctx.emu.set(iu.LIST_SCROLL, 2)
    assert ce.rope_press(ctx, ["HP UP", "x 1", ">ESCAPE ROPE", "x 1"]).rule == "item_use"
    assert ce.rope_press(ctx, [">USE", "TOSS"]).button == "A"
    assert ce.rope_press(ctx, ["Hello there"]).button == "B"
