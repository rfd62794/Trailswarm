"""Cap on repeated blocked presses of one tile+direction (Route 24, 2026-11-07: ~1500 UP presses into a beaten trainer).

Pure bookkeeping: ``note`` counts consecutive failed moves of the same (position, button) and says when the cap is hit.
The caller then marks the tile ahead temporarily blocked and replans."""
from __future__ import annotations

BLOCKED_PRESS_CAP = 20      # consecutive blocked presses of one tile+direction before the tile ahead is given up on
CAP_BLOCK_FRAMES = 960      # how long a capped tile stays out of routing (4x the person-in-the-way decay)


def note(streak: dict, before: tuple, name: str, moved: bool) -> bool:
    """Record one move press. True when this press makes the (before, name) streak reach the cap (the streak is then reset)."""
    if moved:
        streak.clear()
        return False
    key = (before, name)
    if key not in streak:
        streak.clear()  # a different tile/direction: the old streak is over
    streak[key] = streak.get(key, 0) + 1
    if streak[key] >= BLOCKED_PRESS_CAP:
        del streak[key]
        return True
    return False
