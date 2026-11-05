"""advance_dialog: keep text boxes moving (naming keyboard, stuck-menu / stuck-dialog B, otherwise A)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import is_menu


class NamingKeyboard(BehaviourBase):
    name = "naming_keyboard"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.box and any("A B C D E" in ln for ln in ctx.view.lines)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        # the naming KEYBOARD: START = END (B only deletes letters)
        if ctx.replay_ctx:
            ctx.replay = []; rp = ctx.replay_ctx; rp["demo"]["grade"] = -1; ctx.pop("replay_ctx")
            ctx.log("[the replayed beat led into the keyboard: graded BAD]", "res")
        return Decision("START", "keyboard_start", "naming keyboard open: START ends it (default name)")


class AdvanceDialog(BehaviourBase):
    name = "advance_dialog"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.box

    def step(self, ctx: ExplorerContext) -> Decision | None:
        tm_now = ctx.view.tm
        if ctx.box_streak >= 12 and is_menu(tm_now):
            return Decision("B", "menu_stuck_b", "a menu has stayed open for 12 presses - pressing B to back out")
        if ctx.box_streak >= 60:
            return Decision("B", "dialog_stuck_b", "a dialog has run 60 presses - pressing B in case it is a hidden prompt")
        if is_menu(tm_now):
            return None  # a menu: the menu behaviour chooses
        return Decision("A", "advance_a", "a text box is open - finishing the interaction before moving")

    def failed(self, ctx: ExplorerContext) -> bool:
        return ctx.box_streak >= 60
