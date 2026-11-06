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
