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
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines, lead_level
from pokeagent.explorer.world import DUNGEON_MAPS
from pokeagent.knowledge import team_plan, trainers
from pokeagent.knowledge.party import our_party, trainer_mon
from pokeagent.magikarp import party_species, trainee_slot
from pokeagent.ramstructs import read_party

MAX_PRESSES = 40          # one reorder is about 10 presses; more means the menus are not what we think
RETRY_AFTER_STEPS = 300   # after an abandoned attempt
CALM_FRAMES = 8           # the screen must have been still this long before the first press (no cutscene, no fade)
PACE_FRAMES = 8           # frames to wait between presses


def species_names(emu) -> list[str]:
    names = (ROM_KB or {}).get("name_of_internal", {})
    return [names.get(str(s), f"#{s}") for s in party_species(emu)]


def trainee_home(ctx: ExplorerContext) -> int:
    """Where the trainee Magikarp belongs: first outside (sent out and swapped on turn one), LAST inside a dungeon, where
    every fight is a wild one on the way to the exit and the turn-one swap costs ~20 presses a battle (Mt Moon 2026-11-05)."""
    return max(0, ctx.emu.read(0xD163) - 1) if ctx.view.m in DUNGEON_MAPS else 0


def _opponent(ctx: ExplorerContext) -> list:
    """[(level, species)] the matchup lead is chosen for, or []: the strongest unbeaten trainer party on
    the map while trainer_hunt has named an engage target here, else the stage boss's party while the
    next unmet goal is a boss stage and the training gate is closed (an open gate keeps the trainee lead)."""
    t = ctx.trainer_target
    if t is not None and t[0] == ctx.view.m:
        from pokeagent.explorer import trainer_ledger
        mons = [e.mons for e in trainer_ledger.ledger_for(ctx).entries(t[0]) if e.state != "beaten" and e.mons]
        if mons:
            return max(mons, key=lambda p: sum(lv for lv, _ in p))
    from pokeagent.explorer.training import BOSS_LABEL, stage_goal
    goal = stage_goal(ctx.goals())
    if goal and goal in BOSS_LABEL and not (0 < lead_level(ctx.emu) < (ctx.train_need or 0)):
        return trainers.boss_party(goal, starter_names=species_names(ctx.emu)) or (
            trainers.strongest_on_mt_moon() if goal == "to_mt_moon" else [])
    return []


def want_home(ctx: ExplorerContext) -> tuple[int, int, str] | None:
    """(src, want, why) for the next reorder, or None when the party order stands: the member at ``src``
    should sit at ``want`` (SWITCH swaps the two slots). Before a known boss/trainer target the lead is
    the matchup pick (team_plan.choose_lead); on a grind the lowest band breaker leads for the shared
    exp; otherwise the Magikarp trainee's home, exactly as before."""
    opp = _opponent(ctx)
    if opp:
        party = our_party(ctx.emu)
        theirs = [m for lv, n in opp if (m := trainer_mon(n, lv))]
        if party and theirs:
            src = team_plan.choose_lead(party, theirs, None)
            if src != 0:
                names = species_names(ctx.emu)
                who = names[src] if src < len(names) else f"slot {src + 1}"
                return (src, 0, f"matchup lead {who} for {theirs[0].name}")
            return None
    slot = trainee_slot(ctx.emu)
    if slot is not None:
        home = trainee_home(ctx)
        return (slot, home, "trainee home") if slot != home else None
    brk = team_plan.of(ctx).get("breakers") or ()
    if brk and 0 < lead_level(ctx.emu) < (ctx.train_need or 0):
        s = team_plan.trainee_slot(read_party(ctx.emu), ctx.train_member, brk)
        if s is not None and s != 0:
            return (s, 0, "exp rotation: the lowest band breaker leads the grind")
    return None


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
