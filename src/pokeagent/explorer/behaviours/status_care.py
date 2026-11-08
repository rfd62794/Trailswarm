"""status_care behaviour: cure a poisoned party member before the poison faints it on the road.

The pure table is explorer.status_care.decide; this behaviour carries the decision out. ``steps_to_heal`` is the
walk to the nearest known Pokecenter (economy.outside_use.walk_to_center, in FRAME_WALK tiles). Item use is the
field-Potion machinery (cave_escape.rope_press -> item_use.item_step), which CAN target a party slot
(``party_target``): START -> ITEM -> scroll to the item -> USE -> pick the poisoned slot. A used cure must VERIFY:
the poison bit clears within VERIFY_STEPS presses of the item leaving the bag, and a failed use is not retried past
MAX_TRIES (then the walk fallback applies). The walk is explorer.heal_walk: a request kept in the status-care
state that THIS behaviour carries out press by press (it runs before PlanGoal) until the nurse has healed the party or
the walk is abandoned with a logged reason. (``ctx.center_intent`` only means "inside a center on purpose"; PlanGoal
clears it on the road, so it cannot carry a request.) ``applies`` is a pure read; every action lives in ``step``.
Never inside a battle (battle poison is the battle behaviours'), never while a boss segment's fight step runs
(ctx.proc / battling guards).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.cave_escape import rope_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer import heal_walk
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.economy.prices import ANTIDOTE, FULL_HEAL, HEAL_HP, REVIVE
from pokeagent.explorer.status_care import (ITEM_NAME, MAX_TRIES, CareDecision, MonStatus, decide, of, record_row,
                                            status_kinds, steps_to_faint)
from pokeagent.explorer.trainee_gate import trainee_check, trainee_ok
from pokeagent.goals import bag_contents
from pokeagent.legs import grid as G
from pokeagent.ramstructs import read_party

RECHECK_EVERY = 10   # steps between care re-evaluations while a member is poisoned (untuned first value)
VERIFY_STEPS = 20    # presses after the item left the bag in which the poison bit (or HP for a Revive) must move
MAX_PRESSES = 60     # one use sequence's press budget (a party pick is ~15 presses)


def _rows(emu) -> list[MonStatus]:
    return [MonStatus(i, p.hp, p.max_hp, status_kinds(p.status)) for i, p in enumerate(read_party(emu))]


def _heal_steps(ctx: ExplorerContext) -> float | None:
    walk = outside_use.walk_to_center(ctx)
    return walk[0] / G.FRAME_WALK if walk else None


class StatusCare(BehaviourBase):
    name = "status_care"

    def applies(self, ctx: ExplorerContext) -> bool:
        """Pure read. Walk / sequence / request in flight own the screen; else a poison to care for or an
        ineligible trainee (whose gate actions run in step)."""
        st = of(ctx)
        if ctx.view.battling or ctx.in_battle:
            return False       # a fight interrupted the sequence: step drops it after the battle
        if st.get("seq") is not None or st.get("request") is not None or st.get("walk") is not None:
            return True        # a started sequence, a cure request or a heal walk owns the screen until it ends
        if ctx.view.box or ctx.proc is not None or ctx.center_intent is not None:
            return False
        if not trainee_check(ctx).ok:
            return True
        if not any("poison" in status_kinds(p.status) for p in read_party(ctx.emu) if p.hp > 0):
            return False
        sig = tuple(p.status for p in read_party(ctx.emu))
        return sig != st.get("sig") or ctx.step >= st.get("next_check", 0)   # a status change re-evaluates at once

    def step(self, ctx: ExplorerContext) -> Decision | None:
        st = of(ctx)
        seq = st.get("seq")
        if seq is not None and seq.get("battle", ctx.battles) != ctx.battles:
            st["seq"] = seq = None   # a fight interrupted the sequence: drop it, re-evaluate
        if seq is None and st.get("walk") is None:
            trainee_ok(ctx)          # the gate's actions (counters, log row, heal walk / cure request) live here
        if st.get("seq") is not None:
            return self._use(ctx, st, st["seq"])
        req = st.pop("request", None)
        if req is not None:   # trainee_gate asked for a cure on a specific slot (a Revive or an Antidote)
            st["seq"] = {"item": req[0], "slot": req[1], "presses": 0, "tries": st.get("tries", 0), "battle": ctx.battles,
                         "bag0": bag_contents(ctx.emu).get(req[0], 0), "used_at": None}
            return self._use(ctx, st, st["seq"])
        if st.get("walk") is not None:
            return heal_walk.step(ctx)
        sig = tuple(p.status for p in read_party(ctx.emu))
        if sig != st.get("sig"):
            st["sig"], st["items_out"], st["tries"] = sig, False, 0
        if not any("poison" in status_kinds(p.status) for p in read_party(ctx.emu) if p.hp > 0):
            return None
        party = _rows(ctx.emu)
        steps = _heal_steps(ctx)
        dec = decide(party, bag_contents(ctx.emu), steps)
        if dec.action in ("antidote", "potion") and st.get("items_out"):
            dec = CareDecision("walk_to_center" if steps is not None else "nothing_available", dec.slot, None,
                               f"{dec.why} (items exhausted)")
        st["next_check"] = ctx.step + RECHECK_EVERY
        if (dec.action, dec.slot, dec.item) != st.get("last"):
            st["last"] = (dec.action, dec.slot, dec.item)
            worst = min((m for m in party if "poison" in m.kinds and m.hp > 0),
                        key=lambda m: steps_to_faint(m.hp), default=None)
            ctx.log(f"[status_care] slot {worst.slot} poisoned HP {worst.hp}/{worst.max_hp}: {steps_to_faint(worst.hp)} steps "
                    f"to faint, {_heal_text(steps)} to the nurse -> {dec.action}: {dec.why}]", "res")
            record_row(ctx, {"event": "decision", "action": dec.action, "slot": dec.slot, "item": dec.item, "why": dec.why,
                             "species": worst.slot, "hp": worst.hp, "max_hp": worst.max_hp,
                             "steps_to_faint": steps_to_faint(worst.hp), "steps_to_heal": steps})
        if dec.action == "walk_to_center":
            heal_walk.start(ctx, f"status_care: {dec.why}")   # a request that outlives PlanGoal steps
            return heal_walk.step(ctx)
        if dec.action in ("antidote", "potion") and dec.slot is not None and dec.item is not None:
            st["seq"] = {"item": dec.item, "slot": dec.slot, "presses": 0, "tries": st.get("tries", 0), "battle": ctx.battles,
                         "bag0": bag_contents(ctx.emu).get(dec.item, 0), "used_at": None}
            return self._use(ctx, st, st["seq"])
        return None   # "none" or "nothing_available": logged once above; exploration continues (other guards own it)

    # --- the item-use sequence (rope_press machinery; a party slot is targetable via party_target) ---
    def _use(self, ctx: ExplorerContext, st: dict, seq: dict) -> Decision | None:
        party = read_party(ctx.emu)
        mon = party[seq["slot"]] if seq["slot"] < len(party) else None
        spent = bag_contents(ctx.emu).get(seq["item"], 0) < seq["bag0"]
        if spent and seq["used_at"] is None:
            seq["used_at"] = seq["presses"]
        if self._success(mon, spent, seq["item"]):
            st["seq"], st["tries"] = None, 0
            ctx.log(f"[status_care: {ITEM_NAME[seq['item']]} used on slot {seq['slot']}]", "res")
            record_row(ctx, {"event": "item_used", "item": seq["item"], "slot": seq["slot"], "presses": seq["presses"]})
            return Decision("B", "status_care_close", "status care done: closing the menus") if ctx.view.lines else None
        if seq["used_at"] is not None and seq["presses"] - seq["used_at"] > VERIFY_STEPS:
            return self._fail(ctx, st, seq, f"{ITEM_NAME[seq['item']]} used but slot {seq['slot']} unchanged after {VERIFY_STEPS} presses")
        if seq["presses"] >= MAX_PRESSES:
            return self._fail(ctx, st, seq, f"not done in {MAX_PRESSES} presses")
        seq["presses"] += 1
        ctx.item_attempts = 0   # the item list's attempt counter is per battle; this sequence has its own budget
        return rope_press(ctx, ctx.view.lines, seq["item"], ITEM_NAME[seq["item"]], "status care", seq["slot"])

    @staticmethod
    def _success(mon, spent: bool, item: int) -> bool:
        """The item did its job: a heal item once drunk (poison stays, HP is up), a Revive once the mon stands,
        an Antidote/Full Heal once the poison bit is gone."""
        if item in HEAL_HP:
            return spent
        if item == REVIVE:
            return mon is not None and mon.hp > 0
        return mon is not None and "poison" not in status_kinds(mon.status)

    def _fail(self, ctx: ExplorerContext, st: dict, seq: dict, why: str) -> Decision:
        st["tries"] = seq["tries"] + 1
        st["seq"] = None
        record_row(ctx, {"event": "use_failed", "item": seq["item"], "slot": seq["slot"], "tries": st["tries"], "why": why})
        if st["tries"] >= MAX_TRIES:
            st["items_out"] = True   # write the item off for this poisoning: the next decision walks instead
            if _heal_steps(ctx) is not None:
                heal_walk.start(ctx, "status_care: item use failed")
        ctx.log(f"[status_care: {why} ({st['tries']}/{MAX_TRIES})]", "res")
        return Decision("B", "status_care_fail", f"status care: {why}; backing out")


def _heal_text(steps: float | None) -> str:
    return f"{steps:.0f}" if steps is not None else "no known route"
