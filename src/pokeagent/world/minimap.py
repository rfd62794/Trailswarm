"""Minimap maths (pure): the visible viewport as a rectangle on a small copy of the world, and click -> world point."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MiniMap:
    world_w: float
    world_h: float
    max_w: float = 220.0      # the box fits inside max_w x max_h keeping the world's aspect
    max_h: float = 160.0

    @property
    def scale(self) -> float:
        return min(self.max_w / self.world_w, self.max_h / self.world_h)

    @property
    def size(self) -> tuple[float, float]:
        return self.world_w * self.scale, self.world_h * self.scale

    def viewport_rect(self, visible: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """The world rectangle ``(x0, y0, x1, y1)`` on screen, as box pixels, clipped to the box."""
        w, h = self.size
        s = self.scale
        x0, y0, x1, y1 = (max(0.0, min(w, visible[0] * s)), max(0.0, min(h, visible[1] * s)),
                          max(0.0, min(w, visible[2] * s)), max(0.0, min(h, visible[3] * s)))
        return x0, y0, x1, y1

    def to_world(self, mx: float, my: float) -> tuple[float, float]:
        """A click at box pixel (mx, my) -> the world pixel it stands for (clamped to the world)."""
        s = self.scale
        return max(0.0, min(self.world_w, mx / s)), max(0.0, min(self.world_h, my / s))

    def contains(self, mx: float, my: float) -> bool:
        w, h = self.size
        return 0 <= mx <= w and 0 <= my <= h

    def agent_dot(self, wx: float, wy: float) -> tuple[float, float]:
        return wx * self.scale, wy * self.scale
