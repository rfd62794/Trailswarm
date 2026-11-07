"""shop: the reusable Poke Mart procedure, ``buy(emu, item_id, qty)``. Every step is verified on the screen / RAM.

Menu flow (ROM-verified 2026-11-05, Viridian Mart map 42, see docs/KNOWLEDGE.md): talk to the clerk -> BUY/SELL/QUIT
(wTextBoxID 14) -> BUY -> item list (13; stock in wItemList, one price per item) -> item -> quantity box "x01 Y200"
(UP/DOWN +-1, wrapping 1 <-> 99; RIGHT/LEFT do nothing) -> A -> "<item>? That will be YN. OK?" YES/NO (20) -> YES -> "Here you are!" -> list again
-> B -> BUY/SELL/QUIT -> B closes. The wrapper blocks (headless) and returns a BuyResult; it never exceeds MAX_PRESSES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pokeagent.emulator import Button, Emulator
from pokeagent.goals import bag_contents
from pokeagent.ramworld import MENU_ITEM, TEXT_BOX_ID, read_money
from pokeagent.screentext import CHARMAP

TB_MENU, TB_LIST = 14, 13  # wTextBoxID values seen in a Mart (the YES/NO box is read from the screen: its id varies)
LIST_SCROLL, ITEM_STOCK = 0xCC36, 0xCF7B  # wListScrollOffset; wItemList = [count, ids..., 0xFF]
TILEMAP, YEN, MAX_QTY, MAX_PRESSES, SETTLE_FRAMES = 0xC3A0, 0xF0, 99, 160, 600


@dataclass
class BuyResult:
    ok: bool
    reason: str
    item_id: int
    qty: int
    bought: int = 0
    unit_price: int = 0
    money_before: int = 0
    money_after: int = 0
    bag_before: dict = field(default_factory=dict)
    bag_after: dict = field(default_factory=dict)
    presses: int = 0
    pages: list = field(default_factory=list)  # distinct screen texts seen, in order (the menu texts of the flow)


def rows(emu: Emulator) -> list[str]:
    """All 18 screen rows decoded; the yen tile reads as '$' and the menu cursor as '>' (text only, for matching)."""
    raw = emu.read_range(TILEMAP, 360)
    return ["".join("$" if b == YEN else CHARMAP.get(b, " ") or " " for b in raw[r * 20:(r + 1) * 20]).strip()
            for r in range(18)]


def quantity_box(emu: Emulator) -> tuple[int, int] | None:
    """(quantity, total price) from the 'x03 $600' row of the quantity box, else None."""
    for line in rows(emu):
        m = re.search(r"x(\d\d)\s*\$?\s*(\d+)", line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def stock(emu: Emulator) -> list[int]:
    n = emu.read(ITEM_STOCK)
    return list(emu.read_range(ITEM_STOCK + 1, n)) if 0 < n <= 10 else []


def _cursor(emu: Emulator) -> int:
    return emu.read(LIST_SCROLL) + emu.read(MENU_ITEM)


def _closed(emu: Emulator) -> bool:
    return emu.read(TEXT_BOX_ID) == 0 and not any(r.startswith(">") for r in rows(emu))


class _Pad:
    """Presses with a press budget; ``press(btn, pred)`` ticks until the predicate holds (or SETTLE_FRAMES pass)."""

    def __init__(self, emu: Emulator, res: BuyResult):
        self.emu, self.res = emu, res

    def snap(self) -> None:
        page = " | ".join(r for r in rows(self.emu) if r)
        if page and (not self.res.pages or self.res.pages[-1] != page):
            self.res.pages.append(page)

    def wait_for(self, pred) -> bool:
        for _ in range(SETTLE_FRAMES // 4):
            if pred():
                break
            self.emu.tick(4)
        self.snap()
        return bool(pred())

    def press(self, button: Button, pred=None, tries: int = 1) -> bool:
        """Press; with a predicate, wait for it and re-press (up to ``tries``) if the game dropped the input."""
        for _ in range(tries):
            if self.res.presses >= MAX_PRESSES:
                return False
            self.res.presses += 1
            self.emu.press(button, 8, 8)
            if pred is None:
                self.emu.tick(24)
                self.snap()
                return True
            if self.wait_for(pred):
                return True
        return False

    def advance_until(self, pred, button: Button = Button.A, tries: int = 8) -> bool:
        """Text waits for a press to continue (seen in the confirm text): press, re-check, never press once ``pred`` holds."""
        for _ in range(tries):
            if pred():
                return True
            self.press(button)
        return pred()

    def box(self, tb: int):
        return lambda: self.emu.read(TEXT_BOX_ID) == tb


def _fail(res: BuyResult, pad: _Pad, reason: str) -> BuyResult:
    res.ok, res.reason = False, reason
    for _ in range(8):  # back out with B (never buys)
        if _closed(pad.emu):
            break
        pad.press(Button.B)
    res.money_after, res.bag_after = read_money(pad.emu), bag_contents(pad.emu)
    return res


def menu_choice(emu: Emulator) -> str | None:
    """Which of BUY / SELL / QUIT the clerk menu cursor (the '>' glyph) is on, else None."""
    for line in rows(emu):
        m = re.search(r">\s*(BUY|SELL|QUIT)", line)
        if m:
            return m.group(1)
    return None


def cursor_on_buy(emu: Emulator, pad: "_Pad") -> bool:
    """Guard: never press A on the BUY/SELL/QUIT menu unless the cursor is on BUY (UP moves it back; SELL/QUIT are never confirmed)."""
    pad.wait_for(lambda: menu_choice(emu) is not None)  # the cursor is drawn a few frames after the menu opens (seen headless)
    for _ in range(3):
        choice = menu_choice(emu)
        if choice == "BUY":
            return True
        if choice is None:
            return False
        pad.press(Button.UP)
    return menu_choice(emu) == "BUY"


def open_menu(emu: Emulator, pad: _Pad) -> bool:
    """Talk to the clerk (the player already faces the counter): A until the BUY/SELL/QUIT menu is up."""
    for _ in range(12):
        if emu.read(TEXT_BOX_ID) == TB_MENU and any("QUIT" in r for r in rows(emu)):
            return True
        pad.press(Button.A, pad.box(TB_MENU))
    return emu.read(TEXT_BOX_ID) == TB_MENU


def buy(emu: Emulator, item_id: int, qty: int) -> BuyResult:
    """Buy ``qty`` of ``item_id`` from the clerk the player faces. Checks money (BCD) first and the bag + money after."""
    res = BuyResult(False, "start", item_id, qty, money_before=read_money(emu), bag_before=bag_contents(emu))
    pad = _Pad(emu, res)
    if not 1 <= qty <= MAX_QTY:
        return _fail(res, pad, "bad_quantity")
    if not open_menu(emu, pad):
        return _fail(res, pad, "no_buy_menu")  # e.g. the clerk only repeats the parcel line before delivery
    if not cursor_on_buy(emu, pad):
        return _fail(res, pad, "menu_cursor_not_on_buy")  # SELL (or anything else) is never selected
    if not pad.press(Button.A, pad.box(TB_LIST)):
        return _fail(res, pad, "list_not_shown")
    pad.wait_for(lambda: any(r.startswith(">") for r in rows(emu)))  # the list is drawn and takes input
    items = stock(emu)
    if item_id not in items:
        return _fail(res, pad, "not_sold_here")
    for _ in range(len(items)):  # cursor to the item, verified from scroll offset + cursor
        if _cursor(emu) == items.index(item_id):
            break
        pad.press(Button.DOWN)
    if _cursor(emu) != items.index(item_id):
        return _fail(res, pad, "cursor_mismatch")
    if not pad.press(Button.A, lambda: quantity_box(emu) is not None, tries=3):
        return _fail(res, pad, "no_quantity_box")
    res.unit_price = quantity_box(emu)[1]
    if res.unit_price * qty > res.money_before:
        return _fail(res, pad, f"insufficient_money (need {res.unit_price * qty}, have {res.money_before})")
    way = Button.UP if qty - 1 <= 100 - qty else Button.DOWN  # the counter wraps 99 <-> 1; take the shorter way round
    for _ in range(MAX_QTY):  # the box shows the quantity, so every press is checked
        box = quantity_box(emu)
        if box is None or box[0] == qty:
            break
        pad.press(way)
    if quantity_box(emu) != (qty, res.unit_price * qty):
        return _fail(res, pad, f"quantity_mismatch {quantity_box(emu)}")
    pad.press(Button.A)  # A on the quantity box starts "<item>? That will be $N. OK?", which needs presses to finish
    if not pad.advance_until(lambda: any(">YES" in r for r in rows(emu))):
        return _fail(res, pad, "no_confirm_box")
    if not any(str(res.unit_price * qty) in r for r in rows(emu)):
        return _fail(res, pad, "confirm_price_mismatch")
    pad.press(Button.A)  # YES (the cursor starts on it)
    pad.wait_for(lambda: read_money(emu) < res.money_before)
    for _ in range(6):  # "Here you are! Thank you!" -> the list again
        if emu.read(TEXT_BOX_ID) == TB_LIST and quantity_box(emu) is None:
            break
        pad.press(Button.A)
    for _ in range(10):  # B: list -> BUY/SELL/QUIT -> closed
        if _closed(emu):
            break
        pad.press(Button.B)
    res.money_after, res.bag_after = read_money(emu), bag_contents(emu)
    res.bought = res.bag_after.get(item_id, 0) - res.bag_before.get(item_id, 0)
    spent = res.money_before - res.money_after
    res.ok = res.bought == qty and spent == res.unit_price * qty
    res.reason = "ok" if res.ok else f"verify_failed (bought {res.bought}, spent {spent})"
    return res
