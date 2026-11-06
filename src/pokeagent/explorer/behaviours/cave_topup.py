"""cave_topup: drink a POTION from the START menu when the fighter is under half HP inside a dungeon and no fight is on.

2026-11-06: cave trainers start fights at whatever HP we walk in with, and low-HP losses warp us out to the Pokemon Center
(the exits to Route 4 mid-run). The battle rule only heals mid-fight, when the next hit may already be too big.
Same screen-driven sequence as the escape rope (cave_escape.rope_press): START -> ITEM -> scroll to POTION -> USE -> pick the
fighter. One potion per sequence; it repeats while HP stays low and potions remain.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.cave_escape import rope_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.world import DUNGEON_MAPS
from pokeagent.goals import bag_contents
from pokeagent.magikarp import MAGIKARP
from pokeagent.ramstructs import read_party

POTION = 0x14
TOPUP_BELOW = 0.5       # fighter HP fraction under which a potion is drunk outside a fight
TOPUP_MAX_PRESSES = 40  # one sequence's budget
TOPUP_COOLDOWN = 150    # steps before a failed sequence is retried


def fighter_slot(emu) -> int:
    """Party slot of the Pokemon that does the fighting: the strongest non-Magikarp (slot 0 without a Magikarp)."""
    party = read_party(emu)
    real = [(i, p) for i, p in enumerate(party) if p.species != MAGIKARP] or list(enumerate(party))
    return max(real, key=lambda ip: (ip[1].hp > 0, ip[1].level, ip[1].hp))[0] if real else 0


def wants_topup(ctx: ExplorerContext) -> bool:
    hp, mx = party_hp(ctx.emu)
    return (ctx.view.m in DUNGEON_MAPS and mx > 0 and 0 < hp < mx * TOPUP_BELOW and bag_contents(ctx.emu).get(POTION, 0) > 0
            and ctx.topup_cooldown_until <= ctx.step)


class CaveTopUp(BehaviourBase):
    name = "cave_topup"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling:
            ctx.topup_presses = 0
            return False
        if ctx.topup_presses:
            return True  # a started sequence owns the screen until it ends
        return not ctx.view.box and ctx.proc is None and ctx.rope_presses == 0 and wants_topup(ctx)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        have = bag_contents(ctx.emu).get(POTION, 0)
        if ctx.topup_presses == 0:
            ctx.topup_potions0 = have
        if ctx.view.m not in DUNGEON_MAPS or have < ctx.topup_potions0 or have == 0:
            if ctx.topup_presses and have < ctx.topup_potions0:
                ctx.log(f"[cave top-up: POTION used, fighter HP now {party_hp(ctx.emu)}]", "res")
            ctx.topup_presses = 0
            return Decision("B", "topup_close", "top-up done: closing any menu") if ctx.view.lines else None
        if ctx.topup_presses >= TOPUP_MAX_PRESSES:
            ctx.topup_presses, ctx.topup_cooldown_until = 0, ctx.step + TOPUP_COOLDOWN
            ctx.log(f"[cave top-up: not done in {TOPUP_MAX_PRESSES} presses; trying again after {TOPUP_COOLDOWN} steps]", "res")
            return Decision("B", "topup_give_up", "top-up sequence abandoned")
        ctx.item_attempts = 0
        ctx.topup_presses += 1
        return rope_press(ctx, ctx.view.lines, POTION, "POTION", "fighter under half HP in the cave", fighter_slot(ctx.emu))
