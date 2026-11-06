"""party_order: reorder_party. START -> POKeMON -> member -> SWITCH -> target, verified screen by screen.

Keeps the Magikarp being switch-trained FIRST in the party (it must be the one that gets sent out into battle, then
swapped out on turn one). Runs whenever it is not first - after buying it, and after anything that reshuffles the party.
Every press is chosen from the text now on screen (party_menu.reorder_press), the order itself is checked in RAM, and a
screen that never gets there abandons the attempt and tries again later.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.party_menu import MENU_ITEM, menu_open, reorder_press, screen_lines
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines
from pokeagent.magikarp import party_species, trainee_slot

MAX_PRESSES = 40          # one reorder is about 10 presses; more means the menus are not what we think
RETRY_AFTER_STEPS = 300   # after an abandoned attempt
CALM_FRAMES = 8           # the screen must have been still this long before the first press (no cutscene, no fade)
PACE_FRAMES = 8           # frames to wait between presses


def species_names(emu) -> list[str]:
    names = (ROM_KB or {}).get("name_of_internal", {})
    return [names.get(str(s), f"#{s}") for s in party_species(emu)]


class PartyOrder(BehaviourBase):
    name = "party_order"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling or ctx.in_battle:
            return False
        if ctx.party_order is not None:
            return True
        slot = trainee_slot(ctx.emu)
        return (slot not in (None, 0) and ctx.step >= ctx.order_retry_at and not ctx.view.box
                and ctx.stable_frames >= CALM_FRAMES and not ctx.mash)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        po = ctx.party_order
        slot = trainee_slot(ctx.emu)
        if po is None:
            if slot is None:
                return None
            po = ctx.party_order = {"src": slot, "presses": 0, "wait": 0}
        if po["wait"] > 0:
            po["wait"] -= ctx.opts.frames_per_step
            return no_press("party_order_wait")
        tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
        lines, framed = screen_lines(tm), frame_lines(tm)
        text = " | ".join(lines)
        if slot in (None, 0):  # in order (or the Magikarp is gone): close whatever is still open, then stop
            if menu_open(text) or (framed and ctx.view.box):
                return self._press(po, "B", f"reorder_party: {species_names(ctx.emu)}", "closing the party menus")
            ctx.log(f"[reorder_party: {species_names(ctx.emu)}]", "res")
            ctx.party_order = None
            return no_press("party_order_done")
        if po["presses"] >= MAX_PRESSES:
            ctx.party_order = None; ctx.order_retry_at = ctx.step + RETRY_AFTER_STEPS
            ctx.log(f"[reorder_party: gave up after {po['presses']} presses; retrying in {RETRY_AFTER_STEPS} steps]", "res")
            return Decision("B", "reorder_party_failed", "reorder_party abandoned: backing out of the menu")
        btn = reorder_press(lines, framed, ctx.emu.read(MENU_ITEM), slot, 0)
        if btn is None:
            btn = "B" if ctx.view.box else "START"  # an unknown box: close it; the overworld: open the START menu
        names = species_names(ctx.emu)
        target = [names[slot]] + names[:slot] + names[slot + 1:]
        return self._press(po, btn, f"reorder_party: {target}", f"slot {slot} -> 0")

    @staticmethod
    def _press(po: dict, btn: str, rule: str, why: str) -> Decision:
        po["presses"] += 1; po["wait"] = PACE_FRAMES
        return Decision(btn, rule, f"{rule} ({why}), press {po['presses']}")
