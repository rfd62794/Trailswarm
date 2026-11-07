"""use_items: the ONE behaviour that runs the item-use policies (explorer/item_policies) outside battle and outside menus.

It is listed twice in ``default_behaviours()``: ``UseItems(active_only=True)`` right after CaveTopUp, so a started sequence owns the
screen before Menu / AdvanceDialog get it (they would explore the START menu and answer the move-forget prompt by their own rules),
and ``UseItems()`` after Heal / Restock, which is the only one allowed to START a sequence (calm overworld, no menu, no dialog, no
other sequence in progress). Both share ``ctx.item_seq``. Screen-driven like cave_topup: START -> ITEM -> scroll to the item by RAM row
-> USE -> party pick (rope_press), or teach_flow for HM / TM. Success is read from RAM (bag count, the move list, the species, riding),
every press is capped, a failed sequence puts the item on a cooldown, and every success is logged through the economy ledger.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.behaviours.cave_escape import rope_press
from pokeagent.explorer.behaviours.item_use import no_effect_shown
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.item_policies import ids, key_items, policy, uselog
from pokeagent.explorer.item_policies.teach_flow import teach_press, yes_no_open
from pokeagent.explorer.item_policies.view import read_mons
from pokeagent.explorer.party_menu import MENU_ITEM, menu_open, screen_lines
from pokeagent.goals import bag_contents

CALM_FRAMES = 8        # the screen must have been still this long before a sequence starts
CHECK_EVERY = 10       # steps between policy evaluations
MAX_PRESSES = {"teach": 110, "party": 60, "self": 40}
CLOSE_PRESSES = 25     # B presses to get back out to the overworld
COOLDOWN = 400         # steps a failed item is left alone
NO_EFFECT_COOLDOWN = 4000
TEACH_MAX_WAITS = 40   # consecutive unrecognised teach screens before the flow is abandoned
STONE_SETTLE = 30      # presses to wait for the evolution to show after the stone left the bag


def _screen(ctx: ExplorerContext) -> list[str]:
    return screen_lines(ctx.view.tm) if ctx.view.tm else []


class UseItems(BehaviourBase):
    name = "use_items"

    def __init__(self, active_only: bool = False) -> None:
        self.active_only = active_only

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling or ctx.in_battle:
            ctx.item_seq = None
            return False
        if ctx.item_seq is not None:
            return True
        if self.active_only or ctx.view.box or ctx.step < ctx.item_next_check:
            return False
        return (ctx.proc is None and ctx.stable_frames >= CALM_FRAMES and not ctx.mash and ctx.goto is None and ctx.party_order is None
                and ctx.topup_presses == 0 and ctx.rope_presses == 0 and policy.has_candidates(bag_contents(ctx.emu), ctx.opts.item_tms))

    def step(self, ctx: ExplorerContext) -> Decision | None:
        seq = ctx.item_seq
        if seq is None:
            ctx.item_next_check = ctx.step + CHECK_EVERY
            pick = policy.choose(ctx)
            if pick is None:
                return None
            seq = ctx.item_seq = {"pick": pick, "presses": 0, "phase": "use", "state": {}, "closing": 0, "ok": None,
                                  "before": uselog.snapshot(ctx.emu, pick.slot, pick.item), "dec_at": None}
            ctx.log(f"[use_items: {ids.name_of(pick.item)} ({pick.category}) - {pick.reason}]", "res")
        if seq["phase"] == "close":
            return self._close(ctx, seq)
        seq["presses"] += 1
        outcome = self._outcome(ctx, seq)
        if outcome is not None:
            return self._finish(ctx, seq, outcome)
        press = self._press(ctx, seq)
        if press is None:   # the abort has been walked out of: nothing teach-specific is on screen any more
            return self._finish(ctx, seq, "failed")
        return press

    # --- progress -----------------------------------------------------------------------------------------------
    def _outcome(self, ctx: ExplorerContext, seq: dict) -> str | None:
        pick, emu = seq["pick"], ctx.emu
        mons = read_mons(emu)
        if pick.kind == "teach":
            if pick.slot < len(mons) and pick.plan.move in mons[pick.slot].moves:
                return "ok"
        elif pick.item == ids.BICYCLE:
            if emu.read(key_items.WALK_BIKE_SURF_STATE) == key_items.BIKE:
                return "ok"
        else:
            used = bag_contents(emu).get(pick.item, 0) < seq["before"]["bag"]
            if used and seq["dec_at"] is None:
                seq["dec_at"] = seq["presses"]
            if used and pick.category == "stone":
                if pick.slot < len(mons) and mons[pick.slot].species != seq["before"].get("species"):
                    return "ok"
                if seq["presses"] - seq["dec_at"] > STONE_SETTLE:
                    return "failed"
            elif used:
                return "ok"
        if no_effect_shown(_screen(ctx)):
            seq["cooldown"] = NO_EFFECT_COOLDOWN
            return "failed"
        if seq["presses"] > MAX_PRESSES[pick.kind]:
            return "failed"
        return None

    def _press(self, ctx: ExplorerContext, seq: dict) -> Decision | None:
        pick, emu = seq["pick"], ctx.emu
        state = seq["state"]
        if pick.kind == "teach":
            mons = read_mons(emu)
            now = mons[pick.slot].moves if pick.slot < len(mons) else ()
            lines = _screen(ctx)
            hit = teach_press(lines, emu.read(MENU_ITEM), pick.plan, now, state)
            if hit is not None:
                state["inside"], state["waits"] = True, 0
                return Decision(hit[0], hit[1], hit[2])
            if state.get("abort"):
                return None
            if state.get("inside"):  # past USE: an unrecognised screen is text still printing or a list still drawing; never a cursor press
                state["waits"] = state.get("waits", 0) + 1
                text = " ".join(lines).lower()
                if state["waits"] > TEACH_MAX_WAITS:
                    state["abort"] = True
                    return Decision("B", "teach_abort", "the teach flow stopped making sense: backing out")
                if "abandon" in text or "be forgotten" in text or "which move" in text or not ctx.view.box:
                    return no_press("teach_wait", "teach flow: waiting for the prompt to finish drawing")
                return Decision("A", "teach_text", "advancing the teach dialog")
        ctx.item_attempts = 0   # the item list's attempt counter is per battle; this sequence has its own press budget
        dec = rope_press(ctx, ctx.view.lines, pick.item, ids.name_of(pick.item), pick.reason, pick.slot)
        if pick.kind == "teach" and dec.rule == "rope_use" and dec.button == "A":
            state["inside"] = True   # USE is pressed: from here on only teach_flow decides
        return dec

    def _finish(self, ctx: ExplorerContext, seq: dict, outcome: str) -> Decision | None:
        pick = seq["pick"]
        seq["phase"], seq["ok"] = "close", outcome == "ok"
        if outcome == "ok":
            uselog.record(ctx, pick.item, pick.category, pick.reason, seq["before"], uselog.snapshot(ctx.emu, pick.slot, pick.item))
        else:
            ctx.item_cooldown[pick.item] = ctx.step + seq.get("cooldown", COOLDOWN)
            ctx.log(f"[use_items: {ids.name_of(pick.item)} not done ({seq['presses']} presses{', aborted' if seq['state'].get('abort') else ''}); "
                    f"left alone for {seq.get('cooldown', COOLDOWN)} steps]", "res")
        return self._close(ctx, seq)

    def _close(self, ctx: ExplorerContext, seq: dict) -> Decision | None:
        """Back out to the overworld with B. A level-up move prompt (YES/NO) is handed to Menu, which already answers it."""
        lines = _screen(ctx)
        open_menu = ctx.view.box or menu_open(" | ".join(lines))
        if not open_menu or yes_no_open(lines) or seq["closing"] >= CLOSE_PRESSES:
            ctx.item_seq = None
            return None
        seq["closing"] += 1
        return Decision("B", "use_items_close", "item sequence over: closing the menus")
