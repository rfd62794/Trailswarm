"""Follow-ups: never open POKeDEX from the menu explorer; never use a non-healing item for HP (fight/flee instead);
purge false walls learned while a full-screen page was open."""
from __future__ import annotations

from pokeagent.explorer.behaviours.battle import Battle
from pokeagent.explorer.behaviours.item_use import BAG_COUNT, BAG_START
from pokeagent.explorer.behaviours.menu import Menu
from test_battle_types import BATTLE, make_ctx, put_box


def test_menu_explorer_skips_pokedex(tmp_path):
    ctx = make_ctx(tmp_path)
    put_box(ctx, ["> POK DEX", "POKEMON", "ITEM", "SAVE", "OPTION", "EXIT"])
    ctx.refresh()
    d = Menu().step(ctx)
    assert (d.button, d.rule) == ("DOWN", "menu_skip_pokedex")
    ctx = make_ctx(tmp_path)
    put_box(ctx, ["POK DEX", ">POKEMON", "ITEM", "SAVE", "OPTION", "EXIT"])
    ctx.refresh()
    assert Menu().step(ctx).rule == "menu_new_option"  # other rows are still explored


def _hurt_with_bag(tmp_path, bag, kind=1, hp=11, mx=57, rows=("FIGHT PKMN", ">ITEM RUN")):
    mem = {BATTLE: kind, 0xD163: 1, 0xD16C: 0, 0xD16D: hp, 0xD18D: 0, 0xD18E: mx, BAG_COUNT: len(bag),
           **{BAG_START + 2 * i + o: v for i, b in enumerate(bag) for o, v in ((0, b), (1, 1))}}
    ctx = make_ctx(tmp_path, memory=mem)
    put_box(ctx, list(rows))
    ctx.refresh()
    return ctx


def test_antidote_never_stands_in_for_a_potion(tmp_path):
    """Live B2F loop: 11/57 HP, bag ANTIDOTE only. No item rule may fire; a wild fight flees (down/right toward RUN)."""
    ctx = _hurt_with_bag(tmp_path, [0x0B, 0xEA])  # ANTIDOTE, TM34 - no POTION
    d = Battle().step(ctx)
    assert d is not None and not d.rule.startswith(("item_", "potion")) and d.rule.startswith("flee")
    assert d.button == "RIGHT"  # cursor is on ITEM: RIGHT moves it to RUN


def test_trainer_fight_without_a_potion_falls_through_to_fighting(tmp_path):
    ctx = _hurt_with_bag(tmp_path, [0x0B], kind=2)  # trainer: cannot run, no potion
    assert Battle().step(ctx) is None  # no item decision; battle_moves picks the move


def test_item_list_open_with_only_wrong_items_is_closed_not_confirmed(tmp_path):
    ctx = _hurt_with_bag(tmp_path, [0x0B, 0xEA], rows=(">ANTIDOTE", "x 1", "TM34", "x 1"))
    d = Battle().step(ctx)
    assert d.button == "B" and d.rule == "item_list_close"
