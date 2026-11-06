"""Which meaningful event(s) a press produced, judged from the pre/post RAM snapshots and the press frame.

Snapshots are the 8,319 bytes ``ram_diff.snapshot`` takes (WRAM 0xC000-0xDFFF then HRAM 0xFF80-0xFFFE); this
module only reads a handful of well-known addresses from them, so classifying costs no extra emulator reads.
"""
from __future__ import annotations

from typing import Any

from pokeagent.explorer.perceive import is_menu

WRAM_START, WRAM_LEN, HRAM_START, HRAM_LEN = 0xC000, 0x2000, 0xFF80, 0x7F
SNAP_LEN = WRAM_LEN + HRAM_LEN

IN_BATTLE, CUR_MAP, PARTY_COUNT, PARTY_SPECIES, MONEY = 0xD057, 0xD35E, 0xD163, 0xD164, 0xD347
ENEMY_SPECIES, LEAD_HP, LEAD_MAXHP = 0xCFE5, 0xD16C, 0xD18D

TEXT_RULES = (("heal", ("fighting fit", "restore your")), ("shop", ("may i help", "anything else")),
              ("pc", ("turned on", "accessed", "someone's pc", "bill's pc")))


def offset(addr: int) -> int:
    return addr - WRAM_START if addr < HRAM_START else WRAM_LEN + addr - HRAM_START


def addr_of(off: int) -> int:
    return WRAM_START + off if off < WRAM_LEN else HRAM_START + off - WRAM_LEN


def rd(snap: bytes, addr: int, n: int = 1) -> bytes:
    o = offset(addr)
    return snap[o:o + n]


def u16(snap: bytes, addr: int) -> int:
    return int.from_bytes(rd(snap, addr, 2), "big")


def first_line(text: str) -> str:
    return (text or "").split(" | ")[0].strip()[:60]


def classify(pre: bytes, post: bytes, fr: Any, goals_delta: int, last_text: str = "") -> tuple[list[str], dict]:
    """(event types, value context). Value context holds ids/values a changed byte might be a copy of."""
    ev: list[str] = []
    vals: dict[str, Any] = {}
    b0, b1 = rd(pre, IN_BATTLE)[0], rd(post, IN_BATTLE)[0]
    if not b0 and b1:
        ev.append("battle_start"); vals["enemy_species"] = rd(post, ENEMY_SPECIES)[0]; vals["battle_kind"] = b1
    elif b0 and not b1:
        ev.append("battle_end")
    m0, m1 = rd(pre, CUR_MAP)[0], rd(post, CUR_MAP)[0]
    if m0 != m1:
        ev.append("map_change"); vals["map"], vals["prev_map"] = m1, m0
    item = fr.extra.get("item")
    if item:
        ev.append("item_gain" if item["delta"] > 0 else "item_use"); vals["item"], vals["delta"] = item["id"], abs(item["delta"])
    if rd(pre, MONEY, 3) != rd(post, MONEY, 3):
        ev.append("money"); vals["money_bytes"] = list(rd(post, MONEY, 3))
    if goals_delta > 0:
        ev.append("goal")
    if fr.extra.get("event_flags"):
        ev.append("story_flag")
    box0, box1 = fr.box_before, fr.box_after
    if box1 and not box0:
        ev.append("text_open")
    elif box0 and not box1:
        ev.append("text_close")
    if fr.tm2 and fr.tm and is_menu(fr.tm2) and not is_menu(fr.tm):
        ev.append("menu_open")
    if rd(pre, PARTY_COUNT, 7) != rd(post, PARTY_COUNT, 7):
        ev.append("party_change"); vals["party_count"] = rd(post, PARTY_COUNT)[0]; vals["party_species"] = list(rd(post, PARTY_SPECIES, 6))
    low = (fr.text or last_text or "").lower()
    for name, keys in TEXT_RULES:
        if any(k in low for k in keys):
            ev.append("heal" if name == "heal" else "pc_shop")
            break
    if u16(post, LEAD_HP) > u16(pre, LEAD_HP) and not b1 and "heal" not in ev and u16(pre, LEAD_HP) < u16(pre, LEAD_MAXHP):
        ev.append("heal"); vals["hp_after"] = u16(post, LEAD_HP)
    return ev, vals
