"""text_pace: the fastest safe A-press pace through text boxes, menus and YES/NO prompts.

Two parts. (1) ``prompt_waiting``: the box is waiting for input when the blinking down-arrow tile 0xEE shows at
screen row 16, column 18 (ROM-verified 2026-11-05, see docs/KNOWLEDGE.md), so A is pressed the moment it shows, not
after a fixed frame count. (2) ``PaceLearner``: per screen kind, the minimum settle frames after a press that never
dropped an input. It shrinks while presses keep working and grows when a press is dropped (the same page is still
shown after the press). Stored in maps.json under ``text_pace``. Pure: no emulator here (see ``text_press``).
"""
from __future__ import annotations

PROMPT_TILE, PROMPT_ROW, PROMPT_COL = 0xEE, 16, 18  # blinking down arrow in the dialog box
KINDS = ("box", "menu", "yesno", "battle")
MIN_SETTLE, MAX_SETTLE, START_SETTLE = 2, 40, 16  # frames after a press before the screen is read
SHRINK_STEP, SHRINK_AFTER, GROW_FACTOR = 2, 3, 2  # shrink 2 frames after 3 clean presses; double on a drop
HOLD_FRAMES = 4  # button held; the game polls input every frame, 4 is enough and 8 was the old default


def prompt_waiting(tm: bytes) -> bool:
    """True while the text box shows the down-arrow prompt (waiting for A)."""
    i = PROMPT_ROW * 20 + PROMPT_COL
    return len(tm) > i and tm[i] == PROMPT_TILE


def screen_kind(tm: bytes, battling: bool, menu: bool, yesno: bool = False) -> str:
    """The pacing class of what is on screen."""
    if battling:
        return "battle"
    return "yesno" if yesno else "menu" if menu else "box"


class PaceLearner:
    def __init__(self, data: dict):
        self.table: dict = data.setdefault("text_pace", {})

    def _e(self, kind: str) -> dict:
        return self.table.setdefault(kind, {"settle": START_SETTLE, "clean": 0, "drops": 0, "presses": 0})

    def settle(self, kind: str) -> int:
        return self._e(kind)["settle"]

    def record(self, kind: str, dropped: bool) -> int:
        """Learn from one press; returns the new settle frames for ``kind``."""
        e = self._e(kind)
        e["presses"] += 1
        if dropped:
            e["drops"] += 1
            e["clean"] = 0
            e["settle"] = min(MAX_SETTLE, max(e["settle"], MIN_SETTLE) * GROW_FACTOR)
        else:
            e["clean"] += 1
            if e["clean"] >= SHRINK_AFTER:
                e["clean"] = 0
                e["settle"] = max(MIN_SETTLE, e["settle"] - SHRINK_STEP)
        return e["settle"]
