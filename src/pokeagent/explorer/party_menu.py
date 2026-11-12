"""Reading and driving the party screens: pure functions of the on-screen text and the menu cursor.

The party list is a full-screen list WITHOUT a frame (so ``perceive.frame_lines`` sees nothing of it): its rows are
decoded here. Texts verified on the ROM 2026-11-05 (docs/KNOWLEDGE.md): the list says "Choose a POKeMON."; choosing a
member opens STATS / SWITCH / CANCEL; SWITCH asks "Move POKeMON where?". The cursor row is wCurrentMenuItem (MENU_ITEM).
"""
from __future__ import annotations

import re

from pokeagent.ram_symbols import MENU_ITEM
from pokeagent.screentext import CHARMAP


def screen_lines(tm: bytes) -> list[str]:
    """Every readable row of the 20x18 tile map (framed or not); the menu cursor tile reads '>'."""
    out = []
    for r in range(18):
        row = tm[r * 20:(r + 1) * 20]
        text = "".join(">" if b == 0xED else (CHARMAP.get(b, " ") or " ") for b in row)
        text = " ".join("".join(c if c.isprintable() else " " for c in text).split())
        if any(c.isalnum() for c in text):
            out.append(text)
    return out


def toward(cur: int, want: int, confirm: str = "A") -> str:
    """The button that moves a vertical menu cursor from `cur` to `want`, or `confirm` when it is there."""
    return confirm if cur == want else ("DOWN" if cur < want else "UP")


def is_party_screen(text: str) -> bool:
    return bool(re.search(r"Choose a POK|Move POK|Bring out|STATS", text, re.I))


def is_start_menu(text: str) -> bool:
    return bool(re.search(r"OPTION", text) and re.search(r"POK.MON", text) and "EXIT" in text)


def menu_open(text: str) -> bool:
    return is_party_screen(text) or is_start_menu(text)


def start_menu_target(lines: list[str]) -> int | None:
    """Row index of POKeMON in the START menu's own lines (POKeDEX above it once the dex is owned)."""
    rows = [ln.replace(">", "").strip() for ln in lines]
    return next((i for i, r in enumerate(rows) if re.match(r"POK.MON", r)), None)


def reorder_press(lines: list[str], start_lines: list[str], cur: int, src: int, dst: int) -> str | None:
    """Next button to swap party slot `src` with `dst`, from START (or the overworld) all the way through.

    `lines` is the whole screen (screen_lines), `start_lines` the framed rows only (the START menu sits over map tiles
    that decode as noise). None when the screen is none of the menus (the caller presses START).
    SWITCH is item 1 of STATS/SWITCH/CANCEL.
    """
    text = " | ".join(lines)
    if re.search(r"Move POK.*where", text, re.I):
        return toward(cur, dst)
    if "STATS" in text and "SWITCH" in text:
        return toward(cur, 1)
    if re.search(r"Choose a POK", text, re.I):
        return toward(cur, src)
    if is_start_menu(" | ".join(start_lines)):
        row = start_menu_target(start_lines)
        return toward(cur, row) if row is not None else "B"
    return None
