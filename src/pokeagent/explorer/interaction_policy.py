"""interaction_policy: when is talking to a known interaction worth it again? One table of named rules.

``decide(entry, need)`` returns (talk, rule). The rule string goes into the decision log, so a skipped talk explains
itself. ``need`` is what the agent wants right now (see ``Need``), never a position or an NPC name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pokeagent.explorer.interaction_types import BLOCKER, GIVER, HEALER, INFO, PC, SHOP, SIGN, STORY, TRAINER, VENDOR

HEAL_BELOW = 0.5  # any mon below this fraction (or fainted) needs healing; same figure as the planner's road threshold


@dataclass
class Need:
    """The agent's current wants. All fields default to 'want nothing'."""
    party: list = field(default_factory=list)  # [(hp, max_hp)] per mon
    wants_item: bool = False  # a goal or the item budget wants something bought / from the PC
    bag_ids: frozenset = frozenset()
    goal_changed: bool = False  # the goal moved on since a blocker was recorded
    nearest_healer: bool = True  # this entry is the nearest known healer by route length
    trainer_beaten: bool = False
    run_id: str = ""  # the current run; a giver's "done" only counts when it was stamped by this run (maps.json outlives runs)
    reread: bool = False  # a goal or remote order explicitly wants this spot read again (goto target, centre intent)


def needs_heal(party: list, below: float = HEAL_BELOW) -> bool:
    return any(mx and (hp == 0 or hp / mx < below) for hp, mx in party)


def nearest_healer(routes: dict) -> str | None:
    """Key of the healer with the shortest route length (ties: first key), None if there is none."""
    return min(routes, key=lambda k: (routes[k], k)) if routes else None


R_MEMORISED = "info/sign: memorised - talking again teaches nothing"
R_GIVER_DONE = "giver: already given this run - once only"
R_GIVER_FIRST = "giver: not yet given - talk once"
R_HEAL_YES = "healer: party needs healing and this is the nearest healer"
R_HEAL_NO = "healer: nobody needs healing"
R_HEAL_FAR = "healer: a nearer healer is known"
R_WANT = "shop/vendor/pc: a goal or the item budget wants something"
R_NOWANT = "shop/vendor/pc: nothing wanted"
R_TRAINER_DONE = "trainer: beaten once - avoid re-triggering"
R_BLOCKED = "blocker: condition recorded - waiting for a goal change"
R_STORY = "story: scripted - the walk triggers it, never re-talk"
R_NEW = "untyped: unknown spot - talk once"


def decide(entry: dict | None, need: Need) -> tuple[bool, str]:
    """Is it worth talking at this interaction again? ``entry`` None or untyped means never seen: talk once."""
    kind = (entry or {}).get("type")
    if kind is None:
        return True, R_NEW
    if kind in (INFO, SIGN):
        if need.reread:
            return True, "info/sign: a goal explicitly wants it read again"
        return False, R_MEMORISED if (entry.get("pages") or entry.get("text")) else R_NEW
    if kind == GIVER:
        if (entry.get("done") and entry.get("done_run") == need.run_id) or (entry.get("gave") is not None and entry["gave"] in need.bag_ids):
            return False, R_GIVER_DONE
        return True, R_GIVER_FIRST
    if kind == HEALER:
        if not needs_heal(need.party):
            return False, R_HEAL_NO
        return (True, R_HEAL_YES) if need.nearest_healer else (False, R_HEAL_FAR)
    if kind in (SHOP, VENDOR, PC):
        return (True, R_WANT) if need.wants_item else (False, R_NOWANT)
    if kind == TRAINER:
        return (False, R_TRAINER_DONE) if need.trainer_beaten or entry.get("beaten") else (True, "trainer: not yet beaten")
    if kind == BLOCKER:
        return (True, "blocker: goal changed - retry once") if need.goal_changed else (False, R_BLOCKED)
    if kind == STORY:
        return False, R_STORY
    return True, R_NEW
