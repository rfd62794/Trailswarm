"""Answers to YES/NO boxes, move-learning prompts and goal-driven menu choices (moved unchanged)."""
from __future__ import annotations

import re

from pokeagent.explorer.battle import move_value
from pokeagent.goals import GOAL_MENU

# YES/NO boxes: the answer depends on the question that was on screen just before. First match wins; default YES.
YESNO_RULES = [("nickname", "NO"), (" name ", "NO"), ("toss", "NO"), ("deposit", "NO"), ("release", "NO"),
               ("give up", "NO"), (" run ", "NO"), ("", "YES")]  # spaced needles = whole words


STARTERS = ["BULBASAUR", "CHARMANDER", "SQUIRTLE"]


def learn_decision(question: str, current_moves: list[str]) -> tuple[str, str, str | None]:
    """'X is trying to learn Y! ... Delete a move to make room for Y?' -> (YES/NO, why, move to forget)."""
    m = re.search(r"LEARN ([A-Z][A-Z ]+?)[!?]", question.upper())
    new = m.group(1).strip() if m else None
    if not new or not current_moves:
        return "YES", "new move: default accept", None
    worst = min(current_moves, key=move_value)
    if move_value(new) > move_value(worst):  # a status move (0) never replaces a damaging one
        return "YES", f"{new} ({move_value(new):.0f}) beats {worst} ({move_value(worst):.0f})", worst
    return "NO", f"{new} ({move_value(new):.0f}) is not better than our weakest {worst} ({move_value(worst):.0f})", None


def yesno_answer(question: str, starter: str = "any") -> tuple[str, str]:
    q = " " + "".join(ch for ch in question.lower() if ch.isalnum() or ch == " ") + " "  # tolerant of ?,!,é and line breaks
    offered = next((s for s in STARTERS if s.lower() in q.replace(" ", "")), None)
    if offered and "want" in q and "nickname" not in q and "name" not in q.split():  # "So! You want CHARMANDER?"
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
