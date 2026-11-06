"""Zoom/pan maths and hit testing for the world view (pure, no display)."""
from __future__ import annotations

from dataclasses import dataclass

MIN_ZOOM, MAX_ZOOM = 0.04, 4.0


@dataclass
class Viewport:
    """Which part of the world is on screen: ``cx, cy`` = world pixel at the screen centre, ``zoom`` = screen px per world px."""
    world_w: int
    world_h: int
    screen_w: int = 800
    screen_h: int = 600
    cx: float = 0.0
    cy: float = 0.0
    zoom: float = 0.1

    def fit(self) -> None:
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, min(self.screen_w / self.world_w, self.screen_h / self.world_h)))
        self.cx, self.cy = self.world_w / 2, self.world_h / 2

    def resize(self, w: int, h: int) -> None:
        self.screen_w, self.screen_h = max(1, w), max(1, h)

    def to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.cx) * self.zoom + self.screen_w / 2, (wy - self.cy) * self.zoom + self.screen_h / 2

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.screen_w / 2) / self.zoom + self.cx, (sy - self.screen_h / 2) / self.zoom + self.cy

    def pan(self, dsx: float, dsy: float) -> None:
        """Drag the map by a screen delta."""
        self.cx -= dsx / self.zoom
        self.cy -= dsy / self.zoom
        self._clamp()

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Zoom about a screen point so the world point under it stays put."""
        wx, wy = self.to_world(sx, sy)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self.cx = wx - (sx - self.screen_w / 2) / self.zoom
        self.cy = wy - (sy - self.screen_h / 2) / self.zoom
        self._clamp()

    def center_on(self, wx: float, wy: float) -> None:
        self.cx, self.cy = wx, wy
        self._clamp()

    def _clamp(self) -> None:
        self.cx = min(max(self.cx, 0.0), float(self.world_w))
        self.cy = min(max(self.cy, 0.0), float(self.world_h))

    def visible(self) -> tuple[float, float, float, float]:
        """World-pixel rectangle on screen."""
        x0, y0 = self.to_world(0, 0)
        x1, y1 = self.to_world(self.screen_w, self.screen_h)
        return x0, y0, x1, y1


def pick(points: dict[str, tuple[float, float]], vp: Viewport, sx: float, sy: float, radius: float = 14.0) -> str | None:
    """The agent whose world point (px) is nearest the screen position, within ``radius`` screen px."""
    best, best_d = None, radius * radius
    for aid, (wx, wy) in points.items():
        px, py = vp.to_screen(wx, wy)
        d = (px - sx) ** 2 + (py - sy) ** 2
        if d <= best_d:
            best, best_d = aid, d
    return best


def locate(layout, wx: float, wy: float) -> tuple[int, int, int] | None:
    """(map id, cell x, cell y) under a world pixel, or None between maps."""
    from pokeagent.atlas.world import CELL
    cx, cy = int(wx // CELL), int(wy // CELL)
    for m, p in layout.places.items():
        if p.x <= cx < p.x + p.w and p.y <= cy < p.y + p.h:
            return m, cx - p.x, cy - p.y
    return None
