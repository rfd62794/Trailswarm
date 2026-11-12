"""already_out: generic guard - "<name> is already out!" means a behaviour picked the active mon's party slot.

Whatever chose it, back out with B and keep the party list closed for HOLD_STEPS so nothing re-selects the slot.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.party_view import read_battle_view

HOLD_STEPS = 40
PARTY_LIST_MARKERS = ("bring out", "choose a pok")


def already_out_screen(text: str) -> bool:
    return "already out" in " ".join(text.lower().split())


def party_list_screen(text: str) -> bool:
    low = " ".join(text.lower().split())
    return any(m in low for m in PARTY_LIST_MARKERS)


def already_out_decision(text: str, step: int, until: int, hold: int = HOLD_STEPS) -> tuple[bool, int]:
    """(press B?, new hold deadline). The message refreshes the deadline; while it runs, a party list is backed out of."""
    if already_out_screen(text):
        return True, step + hold
    return (step < until and party_list_screen(text)), until


class AlreadyOutGuard(BehaviourBase):
    name = "already_out"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.battling and ctx.view.box and bool(ctx.view.lines)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        text = " ".join(ctx.view.lines)
        press, ctx.already_out_until = already_out_decision(text, ctx.step, ctx.already_out_until)
        if not press:
            return None
        bm = read_battle_view(ctx.emu).battle_mon  # None while wBattleMon is stale: press nothing
        if bm is None or (bm.hp == 0 and not already_out_screen(text)):
            return None  # our battler fainted: the forced "Bring out" list is not the active mon, bring_out drives it
        return Decision("B", "already_out", "party slot of the mon already fighting: backing out, not reselecting it")
