"""battle_yesno: a YES/NO box inside a fight is answered by the dialog rules, not by the battle presses.

The battle behaviours sit before Menu and press A at every box, which takes the cursor's default YES. For the trainer's
"Will <name> change POKeMON?" that opens the party list on the mon already fighting: "<name> is already out!" forever
(43 of 43 such prompts in the 14:50+ swarm runs, 2026-11-07, even after the NO rule in dialog.py landed - Menu never saw them).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.menu import Menu, yesno_box_up
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import frame_lines, is_menu


class BattleYesNo(BehaviourBase):
    name = "battle_yesno"

    def applies(self, ctx: ExplorerContext) -> bool:
        v = ctx.view
        return v.battling and v.box and is_menu(v.tm) and yesno_box_up(frame_lines(v.tm))

    def step(self, ctx: ExplorerContext) -> Decision | None:
        text = " ".join(frame_lines(ctx.view.tm)).lower()
        if "change pok" in text:  # B declines from any cursor spot and returns to FIGHT/PKMN/ITEM/RUN (Robert, 2026-11-07)
            return Decision("B", "decline_switch", "trainer asks to change POKeMON: B declines, back to the battle menu")
        return Menu().step(ctx)
