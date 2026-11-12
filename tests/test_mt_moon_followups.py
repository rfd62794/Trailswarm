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


def test_enclosed_tile_walls_are_purged_on_load_but_real_walls_stay(tmp_path):
    import json
    from pokeagent.explorer.memory import MapMemory
    maps = {"61": {"visited": {"14,26": 5, "15,26": 3, "9,9": 2},
                   "blocked": ["14,26,UP", "14,26,DOWN", "14,26,LEFT", "14,26,RIGHT",   # all four: a page swallowed them
                               "15,26,UP", "15,26,DOWN",                                    # a corridor: two real walls
                               "3,3,UP", "3,3,DOWN", "3,3,LEFT", "3,3,RIGHT",              # never stood on: kept
                               "9,9,UP", "9,9,DOWN", "9,9,LEFT"],                           # three: a dead end, kept
                   "fails": {"14,26,UP": 30, "15,26,UP": 2}, "warps": {"14,26,UP": [60, 1, 1]}, "jumps": {}}}
    path = tmp_path / "maps.json"
    path.write_text(json.dumps({"maps": maps}))
    mem = MapMemory(path)
    d = mem.data["maps"]["61"]
    assert mem.purged_enclosed_walls == 4
    assert sorted(d["blocked"]) == sorted(["15,26,UP", "15,26,DOWN", "3,3,UP", "3,3,DOWN", "3,3,LEFT", "3,3,RIGHT", "9,9,UP", "9,9,DOWN", "9,9,LEFT"])
    assert "14,26,UP" not in d["fails"] and d["fails"]["15,26,UP"] == 2 and d["warps"]["14,26,UP"] == [60, 1, 1]


def _fainted_party(tmp_path, battler_hp=0):
    mem = {BATTLE: 2, 0xD163: 3, 0xD164: 179, 0xD165: 133, 0xD166: 24,
           0xD014: 179, 0xD015: battler_hp >> 8, 0xD016: battler_hp & 255,   # the loaded battler (fainted Wartortle or the live Magikarp)
           0xD16C: 0, 0xD16D: 0,                      # slot 0 fainted
           0xD16C + 0x2C: 0, 0xD16D + 0x2C: 22,       # slot 1 Magikarp, 22 HP
           0xD16C + 0x58: 0, 0xD16D + 0x58: 15}       # slot 2 a real mon, 15 HP
    return make_ctx(tmp_path, memory=mem)


def test_bring_out_picks_a_slot_that_can_fight_not_the_fainted_lead(tmp_path):
    """Mt Moon 1F endless battle: Wartortle (slot 0) fainted, Magikarp alive; A on slot 0 answered 'no will to fight' for 3,300 presses."""
    from pokeagent.explorer.behaviours.bring_out import able_slot, bring_out_press
    ctx = _fainted_party(tmp_path)
    assert able_slot(ctx.emu) == 2                      # a real fighter beats Magikarp
    assert bring_out_press(ctx, ["Bring out which", "POKEMON?"]).button == "DOWN"   # cursor 0 -> 2
    ctx.emu.set(0xCC26, 2)
    assert bring_out_press(ctx, ["Bring out which", "POKEMON?"]).button == "A"
    assert bring_out_press(ctx, ["There no will", "to fight!"]) is None
    ctx.emu.set(0xD16D + 0x58, 0)
    assert able_slot(ctx.emu) == 1                      # only Magikarp left: send it rather than loop
    ctx.emu.set(0xD16D + 0x2C, 0)
    assert able_slot(ctx.emu) is None


def test_bring_out_leaves_the_voluntary_swap_and_the_member_submenu_alone(tmp_path):
    """switch_train sends the Magikarp out and swaps a real mon in: same 'Bring out' header, battler alive. Never touched."""
    from pokeagent.explorer.behaviours.bring_out import bring_out_press
    alive = _fainted_party(tmp_path, battler_hp=22)                                  # the Magikarp on the field is alive
    assert bring_out_press(alive, ["Bring out which", "POKEMON?"]) is None           # voluntary PKMN list
    fainted = _fainted_party(tmp_path)
    assert bring_out_press(fainted, ["Bring out which", "POKEMON?", "STATS", "SWITCH", "CANCEL"]) is None  # submenu row cursor
    fainted.switch_train = {"rule": "switch_train", "presses": 3}
    assert bring_out_press(fainted, ["Bring out which", "POKEMON?"]) is None         # a swap in progress is never overridden


def test_bring_out_drives_the_plain_choose_a_pokemon_forced_list(tmp_path):
    """The forced post-faint list can read 'Choose a POKeMON.' (not 'Bring out'): pick the healthy slot, never B."""
    from pokeagent.explorer.behaviours.bring_out import bring_out_press
    ctx = _fainted_party(tmp_path)
    ctx.emu.set(0xCC26, 1)                                                           # cursor on slot 1 (Magikarp): move to 2
    d = bring_out_press(ctx, ["Choose a POKeMON."])
    assert d is not None and d.button == "DOWN" and d.button != "B"
    ctx.emu.set(0xCC26, 2)
    assert bring_out_press(ctx, ["Choose a POKeMON."]).button == "A"
    assert bring_out_press(_fainted_party(tmp_path, battler_hp=22), ["Choose a POKeMON."]) is None   # voluntary list untouched
