"""cave_topup: a potion from the START menu when the fighter is under half HP inside a dungeon, outside fights."""
from __future__ import annotations

from pokeagent.explorer.behaviours.cave_topup import CaveTopUp, fighter_slot, wants_topup
from pokeagent.explorer.behaviours.item_use import BAG_COUNT, BAG_START, item_step
from test_battle_types import make_ctx

BAG = {BAG_COUNT: 2, BAG_START: 0x14, BAG_START + 1: 3, BAG_START + 2: 0x04, BAG_START + 3: 5}
PARTY = {0xD163: 2, 0xD164: 133, 0xD165: 179,  # Magikarp leads, Wartortle second
         0xD16B: 133, 0xD16C: 0, 0xD16D: 20, 0xD18C: 9, 0xD18D: 0, 0xD18E: 24,
         0xD16B + 0x2C: 179, 0xD16C + 0x2C: 0, 0xD16D + 0x2C: 12, 0xD18C + 0x2C: 21, 0xD18D + 0x2C: 0, 0xD18E + 0x2C: 59}


def test_cave_topup_drinks_a_potion_below_half_hp_only_in_a_dungeon_outside_fights(tmp_path):
    ctx = make_ctx(tmp_path, memory={0xD35E: 0x3C, **BAG, **PARTY})
    ctx.refresh()
    assert fighter_slot(ctx.emu) == 1                      # the Wartortle, not the Magikarp
    assert wants_topup(ctx) and CaveTopUp().applies(ctx)
    assert CaveTopUp().step(ctx).button == "START"         # empty screen: open the menu
    ctx.topup_presses = 0
    ctx.emu.set(0xD35E, 0x0E)
    ctx.refresh()
    assert not wants_topup(ctx)                            # outside a dungeon: not this rule
    ctx.emu.set(0xD35E, 0x3C); ctx.emu.set(0xD16D + 0x2C, 50)
    ctx.refresh()
    assert not wants_topup(ctx)                            # 50/59 is over half
    ctx.emu.set(0xD16D + 0x2C, 12); ctx.emu.set(BAG_START + 1, 0); ctx.emu.set(BAG_COUNT, 1)
    ctx.emu.set(BAG_START, 0x04)
    ctx.refresh()
    assert not wants_topup(ctx)                            # no potion left


def test_item_step_party_pick_uses_the_given_slot_outside_fights(tmp_path):
    ctx = make_ctx(tmp_path, memory={0xCC2F: 0, 0xCC26: 0})
    d = item_step(ctx, ["Use item on which", "POKEMON?"], "", 0x14, "POTION", "t", party_target=1)
    assert (d.button, d.rule) == ("DOWN", "item_party_pick")


def test_use_toss_box_over_the_item_list_is_answered_not_scrolled(tmp_path):
    """ROM batch 2026-11-06: after A on POTION the USE/TOSS box covers the list; rows 'x N' made item_step scroll for 40 presses."""
    from pokeagent.explorer.behaviours.cave_escape import rope_press
    ctx = make_ctx(tmp_path, memory={0xD35E: 0x3C, **BAG, **PARTY})
    over = ["HP UP", "x 1", ">POTION", "x 3", ">USE", "TOSS"]
    assert rope_press(ctx, over, 0x14, "POTION").button == "A"
    assert rope_press(ctx, ["POTION", "x 3", "USE", ">TOSS"], 0x14, "POTION").button == "UP"


def test_fighter_slot_is_the_strongest_healthy_member_not_slot_0(tmp_path):
    """The party stands lowest-first: the potion goes to the strongest member (party_hp's fighter), never the weak lead."""
    party = {**PARTY, 0xD164: 7, 0xD165: 4, 0xD16B: 7, 0xD16B + 0x2C: 4}   # a Squirtle line and a Charmander line: no Magikarp
    ctx = make_ctx(tmp_path, memory={0xD35E: 0x3C, **BAG, **party})
    assert fighter_slot(ctx.emu) == 1                             # slot 1 is level 21, slot 0 level 9
    ctx2 = make_ctx(tmp_path, memory={0xD35E: 0x3C, **BAG, **PARTY})
    assert fighter_slot(ctx2.emu) == 1                            # with a Magikarp in the party: the strongest other member


def test_cave_topup_accepts_a_super_potion_and_picks_the_smallest_item(tmp_path):
    only_super = {**BAG, BAG_START: 0x13}
    ctx = make_ctx(tmp_path, memory={0xD35E: 0x3C, **only_super, **PARTY})
    ctx.refresh()
    assert wants_topup(ctx) and CaveTopUp().step(ctx).button == "START" and ctx.heal_item == 0x13
    both = {**BAG, BAG_COUNT: 3, BAG_START + 4: 0x13, BAG_START + 5: 1}
    ctx = make_ctx(tmp_path, memory={0xD35E: 0x3C, **both, **PARTY})
    ctx.refresh()
    CaveTopUp().step(ctx)
    assert ctx.heal_item == 0x13   # fighter missing 47 HP: a Potion would leave 27 missing
    ctx = make_ctx(tmp_path, memory={0xD35E: 0x3C, **both, **PARTY, 0xD16D + 0x2C: 12, 0xD18E + 0x2C: 25})
    ctx.refresh()
    CaveTopUp().step(ctx)
    assert ctx.heal_item == 0x14   # missing 13 HP: the Potion covers it
