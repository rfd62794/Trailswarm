"""Names for segment checkpoints and keys, shared by the demo (src) and the curriculum tools.

A checkpoint file is ``runs/checkpoints/<end>.state`` (written by any run the first time it lands) or
``<end>.best.state`` (the end state of the fastest CONFIRMED solve). A split sub-segment ends at a map, named
``<goal>@<map hex>``; its start state sits between ``GOALS[i-1]`` and ``GOALS[i]``.
"""
from __future__ import annotations

from pokeagent.goals import GOALS

BEST_SUFFIX = ".best"


def map_key(goal: str, map_id: int) -> str:
    return f"{goal}@{map_id:02x}"


def state_goal(stem: str) -> str:
    """The GOALS name a checkpoint stem stands for: 'x.best' -> 'x'; a sub-segment 'g@3c' -> the goal BEFORE g
    (everything earlier than g is done, g itself is not); anything else is returned unchanged."""
    stem = stem.removesuffix(BEST_SUFFIX)
    if "@" in stem:
        g = stem.split("@", 1)[0]
        i = GOALS.index(g) if g in GOALS else 0
        return GOALS[i - 1] if i > 0 else ""
    return stem
