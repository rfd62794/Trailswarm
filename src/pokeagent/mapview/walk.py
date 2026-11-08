"""Facing and walk phase from position change (pure), plus the per-agent read memory.

The overlay asks for the direction a head moved in and which walk frame to show; a preset
without walk frames only ever produces LEFT/RIGHT and phase 0 (a side-on picture), while a
frame-ful one gets all four directions and the two-step alternation.
"""
from __future__ import annotations


def facing_from(prev: tuple[float, float] | None, cur: tuple[float, float],
                walk_frames: bool, last: str = "DOWN") -> str:
    """RIGHT/LEFT when |dx| >= |dy| else DOWN/UP; no change (or no ``prev``) keeps ``last``.
    With ``walk_frames`` False only LEFT/RIGHT are produced and a vertical move keeps last."""
    if not walk_frames and last not in ("LEFT", "RIGHT"):
        last = "RIGHT"
    if prev is None:
        return last
    dx, dy = cur[0] - prev[0], cur[1] - prev[1]
    if not walk_frames:
        return "RIGHT" if dx > 0 else "LEFT" if dx < 0 else last
    if dx == 0 and dy == 0:
        return last
    if abs(dx) >= abs(dy):
        return "RIGHT" if dx > 0 else "LEFT"
    return "DOWN" if dy > 0 else "UP"


def phase_from(index: int, moved: bool, walk_frames: bool) -> int:
    """0 when unmoved or the preset has no frames, else the two poses alternating every 6 steps."""
    if not moved or not walk_frames:
        return 0
    return index // 6 % 2 + 1


class LiveTracker:
    """(facing, phase) per agent across reads: the previous point plus a step counter."""

    def __init__(self, walk_frames: bool) -> None:
        self.walk_frames, self.prev, self.facing, self.steps = walk_frames, {}, {}, {}

    def update(self, agent: str, area: str, x: float, y: float) -> tuple[str, int]:
        last = self.prev.get(agent)
        prev = (last[1], last[2]) if last is not None and last[0] == area else None
        moved = prev is not None and (x, y) != prev
        face = facing_from(prev, (x, y), self.walk_frames, self.facing.get(agent, "DOWN"))
        self.facing[agent] = face
        if moved:
            self.steps[agent] = self.steps.get(agent, 0) + 1
        self.prev[agent] = (area, x, y)
        return face, phase_from(self.steps.get(agent, 0), moved, self.walk_frames)
