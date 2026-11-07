"""Episode accounting from decision records. An episode runs from a decision to the next goal or MAX_PRESSES.

Rewards are sparse: -presses/100, +1 goal, -2 stall (once per episode), -3 blackout, -5 item tossed.
Records are the lines of decisions.jsonl: a press line has `outcome`/`rule`; event lines carry `event`.
"""
from __future__ import annotations

from dataclasses import dataclass

PRESS, GOAL, STALL, BLACKOUT, TOSS = -0.01, 1.0, -2.0, -3.0, -5.0
MAX_PRESSES = 300
NOVELTY_SCALE, NOVELTY_CAP = 0.1, 0.5  # explorer role only: novelty bonus x scale, at most CAP per episode (a goal is +1)
STALL_RULE = "stall_escalate"  # the StallGuard's escalation: the in-process stand-in for the swarm's stall-kill


@dataclass
class Episode:
    point: str
    key: str
    arm: str
    default: str
    presses: int = 0
    reward: float = 0.0
    stalled: bool = False
    done: bool = False
    novelty: float = 0.0

    def add(self, rec: dict) -> bool:
        """Fold in one record; True when the episode just ended."""
        if self.done:
            return False
        event = rec.get("event")
        if event == "novelty":
            room = NOVELTY_CAP - self.novelty
            paid = max(0.0, min(room, NOVELTY_SCALE * rec.get("bonus", 0.0)))
            self.novelty += paid
            self.reward += paid
        elif event == "item_tossed":
            self.reward += TOSS
        elif event == "blackout":
            self.reward += BLACKOUT
        elif event is None:
            self.presses += 1
            self.reward += PRESS
            if rec.get("rule") == STALL_RULE and not self.stalled:
                self.stalled = True
                self.reward += STALL
            if rec.get("outcome") == "goal":
                self.reward += GOAL
                self.done = True
            elif self.presses >= MAX_PRESSES:
                self.done = True
        return self.done
