"""Answers to YES/NO boxes, move-learning prompts and goal-driven menu choices (moved unchanged)."""
from __future__ import annotations

import re

from pokeagent.explorer.battle import move_value
from pokeagent.goals import GOAL_MENU

# YES/NO boxes: the answer depends on the question that was on screen just before. First match wins; default YES.
YESNO_RULES = [("nickname", "NO"), (" name ", "NO"), ("toss", "NO"), ("deposit", "NO"), ("release", "NO"),
               ("give up", "NO"), (" run ", "NO"), ("", "YES")]  # spaced needles = whole words


STARTERS = ["BULBASAUR", "CHARMANDER", "SQUIRTLE"]


def learn_decision(question: str, current_moves: list[str], protected: frozenset | set = frozenset()) -> tuple[str, str, str | None]:
    """'X is trying to learn Y! ... Delete a move to make room for Y?' -> (YES/NO, why, move to forget)."""
    m = re.search(r"LEARN ([A-Z][A-Z ]+?)[!?]", question.upper())
    new = m.group(1).strip() if m else None
    if not new or not current_moves:
        return "YES", "new move: default accept", None
    free = [m for m in current_moves if m not in protected]   # never forget a move the campaign still needs (an HM)
    if not free:
        return "NO", "every move is one the campaign needs", None
    worst = min(free, key=move_value)
    if move_value(new) > move_value(worst):  # a status move (0) never replaces a damaging one
        return "YES", f"{new} ({move_value(new):.0f}) beats {worst} ({move_value(worst):.0f})", worst
    return "NO", f"{new} ({move_value(new):.0f}) is not better than our weakest {worst} ({move_value(worst):.0f})", None


def offered_starter(question: str) -> str | None:
    """The starter named by an Oak's-lab offer ("So! You want the fire POKeMON, CHARMANDER?"), else None."""
    q = " " + "".join(ch for ch in question.lower() if ch.isalnum() or ch == " ") + " "  # tolerant of ?, ! and line breaks
    offered = next((s for s in STARTERS if s.lower() in q.replace(" ", "")), None)
    if offered and "want" in q and "nickname" not in q and "name" not in q.split():
        return offered
    return None


def magikarp_offer(question: str) -> bool:
    """The Mt Moon salesman's offer ("...a swell MAGIKARP for just 500! What do you say?"), not the nickname prompt."""
    q = " " + "".join(ch for ch in question.lower() if ch.isalnum() or ch == " ") + " "
    return "magikarp" in q and " 500 " in q and "nickname" not in q and "name" not in q.split()


def yesno_answer(question: str, starter: str = "any", buy_magikarp: bool = False, offer_text: str = "") -> tuple[str, str]:
    q = " " + "".join(ch for ch in question.lower() if ch.isalnum() or ch == " ") + " "
    pitch = " " + "".join(ch for ch in (offer_text or question).lower() if ch.isalnum() or ch == " ") + " "
    if "magikarp" in pitch and " for just " in pitch and "nickname" not in pitch and not magikarp_offer(pitch):
        return "NO", "a MAGIKARP pitch, but not the 500 offer"
    if magikarp_offer(offer_text or question):  # YES only for this offer at 500, and only while the buy_magikarp goal is open
        return ("YES", "the MAGIKARP offer at 500 (goal buy_magikarp)") if buy_magikarp else ("NO", "MAGIKARP offer, but buy_magikarp is not wanted now")
    offered = offered_starter(question)
    if offered:  # "So! You want CHARMANDER?"
        if starter == "any" or starter.upper() == offered:
            return "YES", f"starter offered: {offered} (wanted {starter})"
        return "NO", f"starter offered: {offered}, but we want {starter}"
    for needle, ans in YESNO_RULES:
        if needle in q:
            return ans, (f"'{needle}' in the question" if needle else "default for confirmations")
    return "YES", "default"


def goal_menu_choice(goals: dict, options: list[str]) -> str | None:
    for goal, wanted in GOAL_MENU.items():
        if not goals.get(goal):
            for w in wanted:
                # Containment, not prefix: an item list drawn over the PC menu reads "DE POTION", "TO CANCEL".
                hit = next((o for o in options if w in o and "CANCEL" not in o), None)
                if hit:
                    return hit
