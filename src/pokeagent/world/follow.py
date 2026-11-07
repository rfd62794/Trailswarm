"""Follow mode: the World view camera rides along with one agent (pure; the view applies it each frame)."""
from __future__ import annotations

from dataclasses import dataclass

LOST_AFTER_S = 10.0   # the followed agent has had no position this long (finished / restarted): stop following
EASE_PER_S = 8.0      # camera catch-up rate: fraction of the remaining distance closed per second (clamped to 1)
SNAP_PX = 2048.0      # a jump this far (world px: a warp, a map change) snaps instead of gliding across Kanto


@dataclass
class Follow:
    agent_id: str | None = None
    last_seen: float = 0.0

    def start(self, agent_id: str, now: float) -> None:
        self.agent_id, self.last_seen = agent_id, now

    def stop(self) -> None:
        self.agent_id = None

    @property
    def active(self) -> bool:
        return self.agent_id is not None

    def target(self, points: dict[str, tuple[float, float]], now: float) -> tuple[float, float] | None:
        """World-px point to centre on, or None. Updates last_seen when the agent is in `points`;
        stops (agent_id -> None) when it has been missing for LOST_AFTER_S."""
        if self.agent_id is None:
            return None
        p = points.get(self.agent_id)
        if p is not None:
            self.last_seen = now
            return p
        if now - self.last_seen > LOST_AFTER_S:
            self.agent_id = None
        return None

    def step(self, vp, target: tuple[float, float], dt: float) -> None:
        """Move vp.cx/vp.cy toward target: snap when the distance > SNAP_PX, else close
        min(1, dt * EASE_PER_S) of the gap. Never changes vp.zoom. Must not set vp.auto_fit back to True."""
        dx, dy = target[0] - vp.cx, target[1] - vp.cy
        if dx * dx + dy * dy > SNAP_PX * SNAP_PX:
            vp.center_on(*target)
        else:
            k = min(1.0, dt * EASE_PER_S)
            vp.center_on(vp.cx + dx * k, vp.cy + dy * k)
