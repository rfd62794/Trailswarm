"""note_filter: which note lines are battle or menu noise, and how a note is pruned of them.

Pure (no IO). Shared by the brain audit (``brain/audit.py``), the clean planner
(``brain/cleanplan.py``) and the ``interaction_prune`` / ``npc_prune`` journal ops.
"""
from __future__ import annotations

import re

BATTLE = re.compile(r"\bwild\b|go! |fainted|got away|exp\. points|sent\s*\|?\s*out|defeated|used [a-z]+!", re.I)
MENU = re.compile(r"pok.dex \||badges|>fight|item run|now saving|saved\s*\|?\s*the game", re.I)


def text_of(e: dict) -> str:
    """A note's ``text`` and every string page, joined by spaces."""
    pages = [p for p in (e.get("pages") or []) if isinstance(p, str)]
    text = e.get("text")
    return " ".join([text if isinstance(text, str) else ""] + pages)


def is_noise(text) -> str | None:
    """``"battle_text"``, ``"menu_text"`` or None for one line of note text."""
    if not isinstance(text, str) or not text:
        return None
    if BATTLE.search(text):
        return "battle_text"
    if MENU.search(text):
        return "menu_text"
    return None


def first_noise(e: dict) -> str | None:
    """The noise reason of the note's ``text``, else of its first flagged page, else None."""
    for line in [e.get("text")] + list(e.get("pages") or []):
        reason = is_noise(line)
        if reason:
            return reason
    return None


def prune_note(entry: dict) -> dict | None:
    """Drop flagged pages and rebuild ``text`` as the first remaining page ("" when none remain).

    Mutates ``entry`` in place and returns the undo payload - the old values of only the keys
    the entry had (``text`` and/or ``pages``) - or None when nothing was flagged. Never creates
    a ``text`` or ``pages`` key.
    """
    if not isinstance(entry, dict) or first_noise(entry) is None:
        return None
    prior = {k: list(entry[k]) if k == "pages" and isinstance(entry[k], list) else entry[k]
             for k in ("text", "pages") if k in entry}
    pages = entry.get("pages")
    kept = [p for p in pages if not is_noise(p)] if isinstance(pages, list) else []
    if "pages" in entry and isinstance(pages, list):
        entry["pages"] = kept
    if "text" in entry:
        first = next((p for p in kept if isinstance(p, str)), "")
        entry["text"] = first
    return prior
