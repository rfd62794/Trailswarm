"""interaction_gate: is the box on screen a conversation an interaction note may record?

A text box is not always talk: a trainer's speech runs into the battle intro, a step can leave the
START menu open, and save screens are menus too. Notes written from those held battle lines and menu
rows (the 2026-11-08 maps.json audit: ~3,209 battle-pattern, ~672 menu-pattern notes). The gate says
"dialogue" only when no battle is flagged and the screen has no menu cursor.
"""
from __future__ import annotations

from pokeagent.explorer.perceive import is_menu

BATTLE_FLAG = 0xD057  # wIsInBattle: 0 overworld, 1 wild, 2 trainer (the flag press.py logs as battle_flag)


def battling(ctx) -> bool:
    """A battle is flagged in RAM or already latched by the battle behaviour (ctx.in_battle)."""
    return bool(ctx.emu.read(BATTLE_FLAG) or ctx.in_battle)


def is_dialogue_state(ctx, tm: bytes) -> bool:
    """True when an open box is conversation, not a battle intro and not a menu/save screen."""
    return not battling(ctx) and not is_menu(tm)
