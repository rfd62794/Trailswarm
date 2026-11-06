"""cave_escape: out of a dungeon by ESCAPE ROPE when HP is critical, nothing heals, and no fight is on.

Inside Mt Moon the training gate is off (plan_goal), so a hurt party has two ways out: a POTION (the battle rule uses it) or
the rope in the bag. The rope drops us at the last Pokemon Center; the planner's heal rule then walks in, and the ladder
walks us back to the cave. Sequence, read off the screen each press: START -> cursor to ITEM -> A -> scroll the bag list to
ESCAPE ROPE by RAM row (item_use) -> A -> USE. Any unexpected state is backed out of with B; ROPE_MAX_PRESSES caps one try.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.item_use import bag_index, item_list_open, item_step, party_prompt_open
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.world import DUNGEON_MAPS
from pokeagent.goals import bag_contents

ESCAPE_ROPE = 0x1D
HEAL_ITEMS = (0x11, 0x12, 0x13, 0x14)  # MAX/HYPER/SUPER POTION, POTION
CRITICAL_HP = 0.25          # fraction of max HP at or below which the rope is wanted
ROPE_MAX_PRESSES = 40       # one try's budget before it is abandoned
ROPE_COOLDOWN = 300         # steps before a failed try is repeated


def wants_rope(ctx: ExplorerContext) -> bool:
    hp, mx = party_hp(ctx.emu)
    bag = bag_contents(ctx.emu)
    return (ctx.view.m in DUNGEON_MAPS and mx > 0 and 0 < hp <= mx * CRITICAL_HP and ESCAPE_ROPE in bag
            and not any(bag.get(i, 0) for i in HEAL_ITEMS) and ctx.rope_cooldown_until <= ctx.step)


def rope_press(ctx: ExplorerContext, lines: list[str], item_id: int = ESCAPE_ROPE, name: str = "ESCAPE ROPE",
               why: str = "cave HP critical", party_target: int | None = None) -> Decision:
    """The next press of an overworld item-use sequence (the rope, or cave_topup's POTION) for the menu on screen."""
    if item_list_open(lines) or party_prompt_open(lines):
        if item_list_open(lines) and bag_index(ctx.emu, item_id) is None:
            return Decision("B", "rope_missing", f"{name} is gone from the bag: closing the list")
        return item_step(ctx, lines, "", item_id, name, why, party_target)
    if any(ln == "USE" or ln == ">USE" for ln in lines):
        return Decision("A" if any(ln == ">USE" for ln in lines) else "UP", "rope_use", f"{name}: choosing USE")
    if any("OPTION" in ln for ln in lines):  # the START menu
        on_item = any(ln.startswith(">ITEM") for ln in lines)
        return Decision("A" if on_item else "DOWN", "rope_open_item" if on_item else "rope_menu_down", "START menu: to ITEM")
    if not lines:
        return Decision("START", "rope_start", f"{why}: opening the START menu for {name}")
    return Decision("B", "rope_back_out", "unexpected screen during the rope sequence: backing out")


class CaveEscape(BehaviourBase):
    name = "cave_escape"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling:
            ctx.rope_presses = 0
            return False
        if ctx.rope_presses:
            return True  # a started sequence owns the screen until it ends
        return not ctx.view.box and ctx.proc is None and wants_rope(ctx)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        if ctx.view.m not in DUNGEON_MAPS or ESCAPE_ROPE not in bag_contents(ctx.emu):
            if ctx.rope_presses:
                ctx.log("[escape rope: used - out of the cave]", "res")
            ctx.rope_presses = 0
            return None
        if ctx.rope_presses >= ROPE_MAX_PRESSES:
            ctx.rope_presses, ctx.rope_cooldown_until = 0, ctx.step + ROPE_COOLDOWN
            ctx.log(f"[escape rope: not done in {ROPE_MAX_PRESSES} presses; trying again after {ROPE_COOLDOWN} steps]", "res")
            return Decision("B", "rope_give_up", "escape rope sequence abandoned")
        ctx.item_attempts = 0  # the item list's attempt counter is per battle; the rope has its own press budget
        ctx.rope_presses += 1
        return rope_press(ctx, ctx.view.lines)
