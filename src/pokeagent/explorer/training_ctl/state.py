"""TrainingState: the six training values the controller shadows, one frozen record per step."""
from __future__ import annotations

from dataclasses import dataclass, fields

FIELDS = ("train_route_live", "episode_live", "gym_hold", "floor_unmet", "train_member", "train_need")


@dataclass(frozen=True)
class TrainingState:
    train_route_live: bool = False
    episode_live: bool = False      # a grind episode is running (ctx._grind_state["episode"])
    gym_hold: bool | None = None    # plan_goal's gym_hold_seen flag; None = not stamped this step
    floor_unmet: bool = False
    train_member: int | None = None
    train_need: int = 0

    def diff(self, other: "TrainingState") -> dict[str, tuple]:
        """{field: (self, other)} for every field that differs; a None gym_hold on either side is 'unknown', not a mismatch."""
        out = {}
        for f in fields(self):
            a, b = getattr(self, f.name), getattr(other, f.name)
            if a != b and not (f.name == "gym_hold" and (a is None or b is None)):
                out[f.name] = (a, b)
        return out
