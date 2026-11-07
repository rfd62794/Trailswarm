"""toss_guard: the agent must never throw a bag item away.

Gen 1 toss flow: bag -> item -> USE/TOSS box -> TOSS -> quantity ("x01", UP/DOWN) -> A -> "Is it OK to toss <ITEM>?"
YES/NO (cursor starts on YES) -> YES -> "Threw away <ITEM>." Each of those screens is recognised from the text rows, and
``toss_veto`` (run by Engine.step on every decision, like retalk_veto) turns any press that could advance the flow
into a back-out: B everywhere, plus UP off TOSS on the USE/TOSS box, A on USE (cave_escape and procedures need it), and
A on the confirm YES/NO only with the cursor on NO. Seen 2026-11-06: the Menu behaviour explored TOSS as an untried
option and the quantity box and the confirm text (no cursor, so not a menu) were stepped through by advance_dialog's A.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: behaviours -> anomalies -> toss_guard would otherwise be a cycle
    from pokeagent.explorer.behaviours.base import Decision

USE_TOSS, QUANTITY, CONFIRM = "use_toss", "quantity", "confirm"


def _bare(line: str) -> str:
    return line.replace(">", "").strip()


def toss_screen(lines: list[str]) -> str | None:
    """Which toss screen the text rows show (CONFIRM / QUANTITY / USE_TOSS), or None."""
    if any("to toss" in ln.lower() for ln in lines):
        return CONFIRM
    has_toss = any(_bare(ln).endswith("TOSS") or _bare(ln).startswith("TOSS") for ln in lines)
    if has_toss and any(re.search(r"\bx\d{2}\b", ln) for ln in lines):  # the quantity box "x01" (the item list's rows read "x 1")
        return QUANTITY
    if has_toss and any(_bare(ln) == "USE" for ln in lines):
        return USE_TOSS
    return None


def _cursor_on(lines: list[str], word: str) -> bool:
    return any(re.search(rf">\s*{word}\b", ln) for ln in lines)


def toss_veto(lines: list[str], decision: Decision) -> str | None:
    """None to let the press through, else why it is replaced by B."""
    screen = toss_screen(lines)
    if screen is None or not decision.button:
        return None
    b = decision.button
    if screen == CONFIRM:
        if b == "A" and _cursor_on(lines, "NO"):
            return None  # NO then A: declining is the one way out besides B
        return "the 'OK to toss' prompt is up: backing out, never confirming a toss"
    if screen == QUANTITY:
        return None if b == "B" else "the toss quantity box is up: backing out, never confirming a toss"
    if _cursor_on(lines, "TOSS"):
        return None if b in ("B", "UP") else "cursor on TOSS in the USE/TOSS box: backing out"
    return None if b in ("A", "B") else "USE/TOSS box: only USE or B, never moving toward TOSS"
