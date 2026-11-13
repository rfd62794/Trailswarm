"""bring_out: after our Pokemon faints the game asks "Bring out which POKeMON?" - pick one that can still fight.

Pressing A on the cursor's default slot 0 (the fainted lead) answers "There's no will to fight!" and the list comes back:
Mt Moon 1F, 2026-11-06, 3,300 presses of that with Magikarp alive in slot 1 (the anomaly detector's endless_battle).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.party_view import read_battle_view, read_party_view
from pokeagent.ram_symbols import MENU_ITEM, SPECIES_MAGIKARP


def able_slot(emu) -> int | None:
    """The party slot to send out: the first non-Magikarp that is not fainted, else any that is not fainted (a Magikarp only
    splashes, but it ends the fight instead of looping); None when everybody has fainted."""
    alive = [s for s in read_party_view(emu).slots if not s.fainted]
    pick = ([s for s in alive if s.species != SPECIES_MAGIKARP] or alive or [None])[0]
    return pick.index if pick is not None else None


def forced_faint_prompt(ctx: ExplorerContext, lines: list[str]) -> bool:
    """The party list asked because our active battler FAINTED. The same 'Bring out which POKeMON?' text also heads the
    voluntary PKMN list (and its STATS/SWITCH/CANCEL submenu), which the switch-training swap drives: leave those alone."""
    text = " ".join(lines)
    low = text.lower()
    # "Bring out which POKeMON?" after a faint AND the plain "Choose a POKeMON." list the forced screen can show: B cannot leave either
    if ("bring out" not in low and "choose a pok" not in low) or "SWITCH" in text or "STATS" in text:
        return False
    if ctx.switch_train is not None:
        return False
    bm = read_battle_view(ctx.emu).battle_mon  # None while wBattleMon is stale (species 0): no battler means no faint
    return bm is not None and bm.hp == 0


def bring_out_press(ctx: ExplorerContext, lines: list[str]) -> Decision | None:
    if not forced_faint_prompt(ctx, lines):
        return None
    target = able_slot(ctx.emu)
    if target is None:
        return None
    cur = ctx.emu.read(MENU_ITEM)
    press = "A" if cur == target else ("DOWN" if cur < target else "UP")
    return Decision(press, "bring_out", f"fainted: sending out party slot {target} (cursor {cur})")
