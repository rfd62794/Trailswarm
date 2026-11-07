"""bring_out: after our Pokemon faints the game asks "Bring out which POKeMON?" - pick one that can still fight.

Pressing A on the cursor's default slot 0 (the fainted lead) answers "There's no will to fight!" and the list comes back:
Mt Moon 1F, 2026-11-06, 3,300 presses of that with Magikarp alive in slot 1 (the anomaly detector's endless_battle).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.magikarp import MAGIKARP

PARTY_COUNT, PARTY_SPECIES, PARTY_HP, MON_STRIDE, MENU_ITEM = 0xD163, 0xD164, 0xD16C, 0x2C, 0xCC26


def able_slot(emu) -> int | None:
    """The party slot to send out: the first non-Magikarp with HP, else any with HP (a Magikarp only splashes, but it ends the
    fight instead of looping); None when everybody has fainted."""
    alive = [i for i in range(min(emu.read(PARTY_COUNT), 6))
             if (emu.read(PARTY_HP + MON_STRIDE * i) << 8 | emu.read(PARTY_HP + MON_STRIDE * i + 1)) > 0]
    real = [i for i in alive if emu.read(PARTY_SPECIES + i) != MAGIKARP]
    return (real or alive or [None])[0]


BATTLER_HP = 0xD015  # wBattleMonHP (2 bytes): our active Pokemon in the fight


def forced_faint_prompt(ctx: ExplorerContext, lines: list[str]) -> bool:
    """The party list asked because our active battler FAINTED. The same 'Bring out which POKeMON?' text also heads the
    voluntary PKMN list (and its STATS/SWITCH/CANCEL submenu), which the switch-training swap drives: leave those alone."""
    text = " ".join(lines)
    if "bring out" not in text.lower() or "SWITCH" in text or "STATS" in text:
        return False
    if ctx.switch_train is not None:
        return False
    return (ctx.emu.read(BATTLER_HP) << 8 | ctx.emu.read(BATTLER_HP + 1)) == 0


def bring_out_press(ctx: ExplorerContext, lines: list[str]) -> Decision | None:
    if not forced_faint_prompt(ctx, lines):
        return None
    target = able_slot(ctx.emu)
    if target is None:
        return None
    cur = ctx.emu.read(MENU_ITEM)
    press = "A" if cur == target else ("DOWN" if cur < target else "UP")
    return Decision(press, "bring_out", f"fainted: sending out party slot {target} (cursor {cur})")
