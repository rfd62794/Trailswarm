"""teach_flow: the TM/HM teaching screens, one press at a time, with a YES/NO guard like the toss guard.

Flow (read off the ROM 2026-11-06, probe on a scratch state): bag -> HM row -> USE/TOSS -> USE -> 'Booted up an HM!' 'It contained CUT!'
-> 'Teach CUT to a POKeMON?' YES/NO -> party list ('Use TM on which POKeMON?', each row ABLE / NOT ABLE) -> learner -> 'X is trying to
learn CUT!' 'But, X can't learn more than 4 moves!' -> 'Delete an older move to make room for CUT?' YES/NO -> 'Which move should be
forgotten?' (the four moves, cursor = wCurrentMenuItem) -> '1, 2 and... Poof! X forgot Y! And... X learned CUT!'.
The guards: YES only on 'Delete an older move' (and on 'Teach'); B in the move list or NO on 'Delete' leads to 'Abandon learning CUT?',
which is answered NO (back to the list) unless the flow was deliberately aborted; A in the move list only when the cursor row IS the
planned move AND the RAM cursor is the planned slot; a NOT ABLE learner aborts before anything is confirmed.
``teach_press`` answers only the teach-specific screens; None = not one of them (the caller's ordinary item-menu driver goes on).
"""
from __future__ import annotations

import re

from pokeagent.explorer.item_policies.hm_teach import HmPlan
from pokeagent.explorer.party_menu import toward

DIALOG = ("booted up", "it contained", "trying to learn", "can learn more", "than 4 moves", "1, 2 and", "poof", "forgot", "and...",
          "learned", "did not learn", "not compatible", "can't learn", "knows")
_STATUS = re.compile(r"^>?\s*(NOT )?ABLE$")
_YES, _NO = re.compile(r"\bYES\b"), re.compile(r"\bNO\b")


def norm(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def yes_no_open(lines: list[str]) -> bool:
    return any(_YES.search(ln) for ln in lines) and any(_NO.search(ln) for ln in lines)


def yes_no_cursor(lines: list[str]) -> str | None:
    for ln in lines:
        m = re.search(r">\s*(YES|NO)\b", ln)
        if m:
            return m.group(1)
    return None


def move_rows(lines: list[str], moves: tuple[str, ...]) -> list[tuple[str, bool]]:
    """(move, cursor on it) for the rows that read as one of the learner's current moves, in screen order."""
    names = {norm(m): m for m in moves}
    out = []
    for ln in lines:
        bare = ln.replace(">", "").strip()
        if norm(bare) in names:
            out.append((names[norm(bare)], ln.lstrip().startswith(">")))
    return out


def party_status(lines: list[str]) -> list[bool]:
    """ABLE (True) / NOT ABLE (False) per party row, in order."""
    return [not ln.replace(">", "").strip().startswith("NOT") for ln in lines if _STATUS.match(ln.strip())]


def teach_press(lines: list[str], cursor: int, plan: HmPlan, moves_now: tuple[str, ...], state: dict) -> tuple[str, str, str] | None:
    """(button, rule, why) for a teach screen, or None. ``cursor`` = wCurrentMenuItem; ``state['abort']`` set by a failed guard."""
    text = " ".join(lines).lower()
    if yes_no_open(lines):
        if "abandon" in text:
            want = "YES" if state.get("abort") else "NO"
            why = "abort: really abandoning" if want == "YES" else "never cancelling into 'didn't learn': back to the move list"
        elif "make room" in text or "delete an older" in text:
            want, why = ("NO", "abort: declining to delete a move") if state.get("abort") else ("YES", f"delete a move to make room for {plan.move}")
        elif "teach" in text:
            want, why = ("NO", "abort: declining to teach") if state.get("abort") else ("YES", f"teaching {plan.move}")
        else:
            return "B", "teach_unknown_yesno", "an unrecognised YES/NO inside the teach flow: backing out"
        if yes_no_cursor(lines) == want:
            return "A", "teach_yesno", f"{want}: {why}"
        return ("UP" if want == "YES" else "DOWN"), "teach_yesno_cursor", f"moving to {want}: {why}"
    rows = move_rows(lines, moves_now)
    if len(rows) == 4:  # the 'Which move should be forgotten?' list: all four moves on screen
        if state.get("abort"):
            return "B", "teach_abort", "aborting: leaving the move list for the 'Abandon learning?' prompt"
        if plan.forget_move is None or plan.forget_slot is None:
            state["abort"] = True
            return "B", "teach_abort", "the move list is up but no overwrite was planned: backing out"
        on = next((m for m, c in rows if c), None)
        if on is not None and norm(on) == norm(plan.forget_move) and cursor == plan.forget_slot:
            return "A", "teach_forget_confirm", f"forgetting {plan.forget_move} (slot {plan.forget_slot}) for {plan.move}"
        if cursor == plan.forget_slot or plan.forget_move not in [m for m, _ in rows]:
            state["abort"] = True  # the cursor is on the planned slot but the row is not the planned move: never press A
            return "B", "teach_abort", f"slot {plan.forget_slot} does not read {plan.forget_move}: aborting"
        return toward(cursor, plan.forget_slot), "teach_forget_cursor", f"move list: cursor {cursor} -> slot {plan.forget_slot} ({plan.forget_move})"
    if "which pok" in text and ("able" in text):
        status = party_status(lines)
        if plan.learner < len(status) and not status[plan.learner]:
            state["abort"] = True
            return "B", "teach_abort", f"party slot {plan.learner} reads NOT ABLE for {plan.move}: aborting"
        return toward(cursor, plan.learner, "A"), "teach_pick_learner", f"{plan.move}: party slot {plan.learner}"
    if any(p in text for p in DIALOG):
        return "A", "teach_text", "advancing the teach dialog"
    return None
