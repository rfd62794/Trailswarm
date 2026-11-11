"""Decision log: runs/<run>/decisions.jsonl, one line per behaviour decision that pressed a button.

Fields: step, behaviour, rule, button, map, x, y, goal_stage, box, battle, outcome, reversal. ``map``/``x``/``y``/
``box``/``battle`` describe the situation the decision was made in; ``outcome`` is what the press did:
moved | blocked | box | map_change | goal | none. ``reversal`` is True when the press undid the previous
position-changing press (landed back on the tile it came from).
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.explorer.perceive import DIRS
from pokeagent.goals import GOALS

FIELDS = ("step", "behaviour", "rule", "button", "map", "x", "y", "goal_stage", "box", "battle", "outcome", "reversal")


def goal_stage(goals: dict) -> str:
    """The first goal not yet reached (the stage the explorer is working on), or "done"."""
    return next((g for g in GOALS if not goals.get(g)), "done")


def classify_outcome(before: tuple, after: tuple, button: str, box_after: bool, goal_reached: bool) -> str:
    if goal_reached:
        return "goal"
    if after[0] != before[0]:
        return "map_change"
    if box_after:
        return "box"
    if after != before:
        return "moved"
    if button in DIRS:
        return "blocked"
    return "none"


def make_record(step: int, behaviour: str, rule: str, button: str, before: tuple, stage: str,
                box: bool, battle: bool, outcome: str, reversal: bool = False) -> dict:
    return {"step": step, "behaviour": behaviour, "rule": rule, "button": button, "map": before[0], "x": before[1],
            "y": before[2], "goal_stage": stage, "box": box, "battle": battle, "outcome": outcome,
            "reversal": reversal}


class DecisionLog:
    def __init__(self, path: Path | str, fh=None) -> None:
        self.path = Path(path)
        self.listeners: list = []  # callables(record): the intervene tracker follows the agent's recent decisions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = fh if fh is not None else self.path.open("a", encoding="utf-8")

    def write(self, record: dict) -> None:
        for fn in self.listeners:
            fn(record)
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()  # a viewer or the selector's seeding can tail the file while the run goes

    def close(self) -> None:
        self._fh.close()
