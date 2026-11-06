"""switch_out: switch_out_lead. The Magikarp leads into every fight and is swapped for the strongest healthy member on turn one.

Gen 1 splits a battle's experience among every Pokemon that TOOK PART, so a Magikarp that is sent out and swapped
straight back still earns its share. Runs after the battle behaviour: a wild fight the agent decides to flee from is
already answered there (RUN with the Magikarp still out), so the flee rule wins; in a trainer fight (no fleeing) the swap
always happens. Never switches into a fainted or sub-25%-HP member (magikarp.switch_candidate); with nobody fit to send
in, the fight goes on as usual.
"""
from __future__ import annotations

import re

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.party_menu import MENU_ITEM, screen_lines, toward
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines
from pokeagent.explorer.behaviours.party_order import species_names
from pokeagent.magikarp import MAGIKARP, MAX_RUNS, switch_candidate
from pokeagent.ramstructs import read_battle_mon

MAX_PRESSES = 30  # a switch is about 6 presses; past this the menus are not what we think: fight on


def switch_press(frames: list[str], screen: list[str], cur: int, target: int) -> str | None:
    """Next button of PKMN -> member -> SWITCH. `frames` are the framed rows (battle menu / submenu), `screen` all rows.

    None when neither the battle menu nor a party screen is up (a text box is scrolling: let it finish).
    """
    text = " | ".join(screen)
    if re.search(r"Move POK.*where", text, re.I):
        return None
    if "SWITCH" in text and "STATS" in text:
        row = next((i for i, r in enumerate(ln for ln in frames if re.search(r"SWITCH|STATS|CANCEL", ln)) if "SWITCH" in r), 1)
        return toward(cur, row)
    if re.search(r"Choose a POK|Bring out", text, re.I):
        return toward(cur, target)
    joined = " ".join(frames)
    if "FIGHT" in joined and "PKMN" in joined:  # the battle menu: FIGHT PKMN / ITEM RUN, cursor somewhere in it
        if re.search(r">\s*PKMN", joined):
            return "A"
        return "RIGHT" if re.search(r">\s*FIGHT", joined) else "UP"  # ITEM/RUN sit under FIGHT/PKMN
    return None


def run_press(frames: list[str]) -> str | None:
    """Next button toward RUN on the battle menu (FIGHT PKMN / ITEM RUN), None when it is not on screen."""
    joined = " ".join(frames)
    if "FIGHT" not in joined or "RUN" not in joined:
        return None
    if re.search(r">\s*RUN", joined):
        return "A"
    return "RIGHT" if re.search(r">\s*ITEM", joined) else "DOWN"  # FIGHT -> ITEM -> RUN, PKMN -> RUN


class SwitchOut(BehaviourBase):
    name = "switch_out"

    def applies(self, ctx: ExplorerContext) -> bool:
        if not ctx.view.battling or ctx.bv is None or ctx.switch_gave_up == ctx.battles:
            return False
        return ctx.switch_train is not None or read_battle_mon(ctx.emu).species == MAGIKARP

    def step(self, ctx: ExplorerContext) -> Decision | None:
        b = read_battle_mon(ctx.emu)
        sw = ctx.switch_train
        if b.species != MAGIKARP:
            if sw is not None:
                ctx.magikarp_shared += 1
                ctx.log(f"[{sw['rule']}: done after {sw['presses']} presses (Magikarp shared {ctx.magikarp_shared} battles)]", "res")
                ctx.switch_train = None
            return None
        target = switch_candidate(ctx.emu)
        tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
        if target is None:
            # Nobody fit to send in. A Magikarp only knows SPLASH: leave a wild fight (the first sighting is logged once),
            # a trainer fight cannot be left, so it carries on as before.
            if ctx.emu.read(0xD057) == 1:
                wild_run = run_press(frame_lines(tm))
                if wild_run is None:
                    return None
                n = ctx.switch_runs[1] + 1 if ctx.switch_runs[0] == ctx.battles else 1
                if wild_run == "A":  # an A on RUN is an attempt; the cursor walk before it is free
                    ctx.switch_runs = (ctx.battles, n)
                    if n > MAX_RUNS:
                        ctx.switch_gave_up = ctx.battles
                        ctx.log(f"[switch_train_run: RUN failed {MAX_RUNS} times this battle - fighting on]", "res")
                        return None
                    ctx.log(f"[switch_train_run: RUN attempt {n}/{MAX_RUNS}]", "res")
                return Decision(wild_run, "switch_train_run", "switch_train: nobody healthy to send in, SPLASH is useless: RUN")
            if ctx.switch_gave_up != ctx.battles:
                ctx.switch_gave_up = ctx.battles
                ctx.log("[switch_train: nobody healthy enough to send in; fighting on]", "res")
            return None
        btn = switch_press(frame_lines(tm), screen_lines(tm), ctx.emu.read(MENU_ITEM), target)
        if btn is None:
            return None  # text scrolling / animation: the usual dialog handling runs
        if sw is None:
            names = species_names(ctx.emu)
            rule = f"switch_train: MAGIKARP L{b.level} -> out, {names[target]} in"
            sw = ctx.switch_train = {"rule": rule, "presses": 0}
        sw["presses"] += 1
        if sw["presses"] > MAX_PRESSES:
            ctx.switch_gave_up = ctx.battles; ctx.switch_train = None
            ctx.log("[switch_train: gave up (menus did not behave); fighting with the Magikarp]", "res")
            return Decision("B", "switch_train_failed", "switch_train abandoned: backing out of the menu")
        return Decision(btn, sw["rule"], f"{sw['rule']} (press {sw['presses']})")
