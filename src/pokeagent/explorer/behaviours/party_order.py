"""party_order: reorder_party. START -> POKeMON -> member -> SWITCH -> target, verified screen by screen.

The party stands LOWEST LEVEL FIRST (Robert 2026-11-12), fainted members last, ties in their current order. Gen 1 sends
slot 0 into every battle and splits XP among the members that took part, so the weakest lead always earns a share and a
stronger member is switched in when needed (switch_out). team_plan.ascending_order is the only ordering rule; this
behaviour just walks the menus. Every press is chosen from the text now on screen (party_menu.reorder_press), the order
itself is checked in RAM, and a screen that never gets there abandons the attempt and tries again later.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.party_menu import MENU_ITEM, menu_open, reorder_press, screen_lines
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines
from pokeagent.knowledge import team_plan
from pokeagent.magikarp import party_species
from pokeagent.ramstructs import read_party

MAX_PRESSES = 40          # one reorder is about 10 presses; more means the menus are not what we think
RETRY_AFTER_STEPS = 300   # after an abandoned attempt
CALM_FRAMES = 8           # the screen must have been still this long before the first press (no cutscene, no fade)
PACE_FRAMES = 8           # frames to wait between presses
HOLD_STEPS = 300          # after a reorder, the matchup / exp-rotation lead is not flipped again this soon unless the team changed


def species_names(emu) -> list[str]:
    names = (ROM_KB or {}).get("name_of_internal", {})
    return [names.get(str(s), f"#{s}") for s in party_species(emu)]


def team_sig(ctx: ExplorerContext) -> tuple:
    """The order-independent team state a reorder may react to: (species, level, fainted) per member, sorted."""
    return tuple(sorted((getattr(m, "species", 0), getattr(m, "level", 0), getattr(m, "hp", 1) == 0)
                        for m in read_party(ctx.emu)))


def _held(ctx: ExplorerContext) -> bool:
    """True while the last reorder is younger than HOLD_STEPS and no level / faint / party change happened since."""
    last = team_plan.of(ctx).get("order_hold")
    return bool(last) and ctx.step - last[0] < HOLD_STEPS and last[1] == team_sig(ctx)


def want_home(ctx: ExplorerContext) -> tuple[int, int, str] | None:
    """(src, want, why) for the next reorder, or None when the party order stands. THE one ordering rule
    (team_plan.ascending_order): lowest level first, fainted members last, ties keep their current order. The
    weakest member leads (Gen 1 gives XP to every member that took part; the lead always gets a share), and a
    stronger member is switched in by switch_out / team_plan when the lead is in danger. SWITCH swaps the two slots."""
    party = read_party(ctx.emu)
    if len(party) < 2:
        return None
    swap = team_plan.next_swap([m.level for m in party], [m.hp <= 0 for m in party])
    if swap is None or _held(ctx):
        return None
    src, want = swap
    names = species_names(ctx.emu)
    who = names[src] if src < len(names) else f"slot {src + 1}"
    return src, want, f"lowest level first: {who} L{party[src].level} -> slot {want + 1}"


class PartyOrder(BehaviourBase):
    name = "party_order"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling or ctx.in_battle:
            return False
        if ctx.party_order is not None:
            return True
        return (want_home(ctx) is not None and ctx.step >= ctx.order_retry_at and not ctx.view.box
                and ctx.stable_frames >= CALM_FRAMES and not ctx.mash)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        po = ctx.party_order
        if po is None:
            w = want_home(ctx)
            if w is None:
                return None
            po = ctx.party_order = {"src": w[0], "want": w[1], "presses": 0, "wait": 0}
            ctx.log(f"[reorder_party: {w[2]}]", "res")
        if po["wait"] > 0:
            po["wait"] -= ctx.opts.frames_per_step
            return no_press("party_order_wait")
        tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
        lines, framed = screen_lines(tm), frame_lines(tm)
        text = " | ".join(lines)
        w = want_home(ctx)
        if w is not None:
            po.setdefault("want", w[1])  # a reorder started before "want" was recorded keeps its target
        if w is None or (w[0], w[1]) != (po["src"], po["want"]):  # ordered, or the ask changed mid-reorder
            if menu_open(text) or (framed and ctx.view.box):
                return self._press(po, "B", f"reorder_party: {species_names(ctx.emu)}", "closing the party menus")
            ctx.log(f"[reorder_party: {species_names(ctx.emu)}]", "res")
            team_plan.of(ctx)["order_hold"] = (ctx.step, team_sig(ctx))
            ctx.party_order = None
            return no_press("party_order_done")
        if po["presses"] >= MAX_PRESSES:
            ctx.party_order = None; ctx.order_retry_at = ctx.step + RETRY_AFTER_STEPS
            ctx.log(f"[reorder_party: gave up after {po['presses']} presses; retrying in {RETRY_AFTER_STEPS} steps]", "res")
            return Decision("B", "reorder_party_failed", "reorder_party abandoned: backing out of the menu")
        btn = reorder_press(lines, framed, ctx.emu.read(MENU_ITEM), po["src"], po["want"])
        if btn is None:
            btn = "B" if ctx.view.box else "START"  # an unknown box: close it; the overworld: open the START menu
        names = species_names(ctx.emu)
        target = list(names)
        target[po["src"]], target[po["want"]] = target[po["want"]], target[po["src"]]  # SWITCH swaps the two slots
        return self._press(po, btn, f"reorder_party: {target}", f"slot {po['src']} -> {po['want']}")

    @staticmethod
    def _press(po: dict, btn: str, rule: str, why: str) -> Decision:
        po["presses"] += 1; po["wait"] = PACE_FRAMES
        return Decision(btn, rule, f"{rule} ({why}), press {po['presses']}")
