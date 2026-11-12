"""item_use: choosing a battle item BY NAME from the bag list, with a per-battle attempt cap.

The old rule pressed A on whatever the bag cursor sat on once the item list was open and POTION was off screen
(the list shows three rows; 2026-11-05 Mt Moon: ANTIDOTE under the cursor, "It won't have any effect." 500+ times in
one battle). Here the target row comes from the bag RAM order (wListCount 0xD31D, then id/qty pairs), the cursor
position from wCurrentMenuItem plus wListScrollOffset (0xCC36), and the press from their difference.
An item that "won't have any effect", or that has been tried MAX_ITEM_ATTEMPTS times this battle, is blocked until
the battle ends, and an open item list we no longer want is closed with B, never confirmed.
"""
from __future__ import annotations

import re

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.ram_symbols import MENU_ITEM, PLAYER_MON_NUMBER

MAX_ITEM_ATTEMPTS = 3  # confirmations of one item per battle before it is written off
POTION = 0x14
HEAL_NAME = {0x14: "POTION", 0x13: "SUPER POTION"}  # economy.heal_items.HEAL_ITEMS
BAG_COUNT, BAG_START = 0xD31D, 0xD31E
LIST_SCROLL = 0xCC36         # wListScrollOffset
PLAYER_MON = PLAYER_MON_NUMBER  # wPlayerMonNumber (kept: tests/test_item_use.py uses iu.PLAYER_MON)
_QTY_ROW = re.compile(r"x ?\d+", re.IGNORECASE)
_NO_EFFECT = re.compile(r"have any\s*effect", re.IGNORECASE)  # the apostrophe glyph does not survive the screen read


def bag_index(emu, item_id: int) -> int | None:
    """Row of ``item_id`` in the bag list (RAM order = display order), or None when it is not carried."""
    n = emu.read(BAG_COUNT)
    if not 0 < n < 21:
        return None
    raw = emu.read_range(BAG_START, 2 * n)
    return next((i for i in range(n) if raw[2 * i] == item_id), None)


def item_list_open(lines: list[str]) -> bool:
    """The bag list shows 'x N' quantity rows; the battle menu, party menu and text boxes never do."""
    return any(_QTY_ROW.fullmatch(ln.strip()) for ln in lines)


def party_prompt_open(lines: list[str]) -> bool:
    return "which" in " ".join(lines).lower()


def no_effect_shown(lines: list[str]) -> bool:
    return bool(_NO_EFFECT.search(" ".join(lines)))


def new_battle(ctx: ExplorerContext) -> None:
    ctx.item_attempts = 0
    ctx.cave_runs = 0
    ctx.item_blocked = set()


def item_is_blocked(ctx: ExplorerContext, item_id: int) -> bool:
    return item_id in ctx.item_blocked or ctx.item_attempts >= MAX_ITEM_ATTEMPTS


def note_screen(ctx: ExplorerContext, lines: list[str], item_id: int) -> None:
    """'It won't have any effect.' means this item cannot help right now: stop offering it this battle."""
    if no_effect_shown(lines) and item_id not in ctx.item_blocked:
        ctx.item_blocked.add(item_id)
        ctx.log(f"[item 0x{item_id:02X} won't have any effect: not retried this battle]", "res")


def _toward(cur: int, want: int) -> str:
    return "A" if cur == want else ("DOWN" if cur < want else "UP")


def item_step(ctx: ExplorerContext, lines: list[str], cur_line: str, item_id: int, item_name: str,
              why: str, party_target: int | None = None) -> Decision | None:
    """The next press toward using ``item_id`` from wherever the battle UI is; None = nothing to do here."""
    emu = ctx.emu
    if item_list_open(lines):
        row = bag_index(emu, item_id)
        if row is None:
            return Decision("B", "item_missing_close", f"{item_name} is not in the bag: closing the item list")
        pos = emu.read(MENU_ITEM) + emu.read(LIST_SCROLL)
        press = _toward(pos, row)
        if press == "A":
            ctx.item_attempts += 1
            return Decision("A", "item_use", f"{why}: using {item_name} (bag row {row}, attempt {ctx.item_attempts})")
        return Decision(press, "item_list_scroll", f"item list: row {pos} -> {item_name} at row {row}")
    if party_prompt_open(lines):  # "Use item on which POKeMON?": the one in the fight, not just slot 1
        slot = emu.read(PLAYER_MON) if party_target is None else party_target  # outside a fight wPlayerMonNumber is stale: the caller says who
        return Decision(_toward(emu.read(MENU_ITEM), slot), "item_party_pick", f"{item_name}: picking the active POKeMON")
    if ">ITEM" in cur_line:
        return Decision("A", "item_open", f"{why}: opening ITEM for {item_name}")
    if "FIGHT" in cur_line or "PKMN" in cur_line:
        return Decision("DOWN", "item_menu_down", "battle menu: down to ITEM")
    if "RUN" in cur_line:
        return Decision("LEFT", "item_menu_left", "battle menu: left to ITEM")
    return None


CATCH_BAG_FRESH = 3  # steps a catch bag press stays "recent": a menu-walking press every step keeps ownership


def catch_owns_bag(ctx: ExplorerContext) -> bool:
    """True while the Catch behaviour is mid item-sequence (ITEM -> ball -> USE): its own press landed within
    CATCH_BAG_FRESH steps and catch_mode is on. Battle runs BEFORE Catch in the registry, so without this its
    "stray item list" close fired on the very list Catch had just opened (A/B alternation, 2026-11-07)."""
    ca = ctx.catch_attempt
    return bool(ctx.catch_mode and ca and ca.get("battle") == ctx.battles   # a stale attempt (blackout/flee) owns nothing
                and ctx.step - ca.get("last", -10**9) <= CATCH_BAG_FRESH)


def close_unwanted_list(ctx: ExplorerContext, lines: list[str]) -> Decision | None:
    """An item list is open but no item is wanted (blocked, healed, or never needed): back out, never confirm."""
    if item_list_open(lines) and not catch_owns_bag(ctx):
        return Decision("B", "item_list_close", "item list open with nothing to use: closing it")
    return None
