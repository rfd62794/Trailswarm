"""Zoom/pan maths and hit testing for the world view (pure, no display)."""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.world import zoom as zsnap

MIN_ZOOM, MAX_ZOOM = 0.04, 8.0


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
    auto_fit: bool = True      # until the user zooms/pans, a resize re-fits the world

    def fit(self) -> None:
        z = zsnap.fit_snap(self.world_w, self.world_h, self.screen_w, self.screen_h)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, z))
        self.cx, self.cy = self.world_w / 2, self.world_h / 2
        self.auto_fit = True

    def resize(self, w: int, h: int) -> None:
        """New screen size: the view centre stays (maximize/restore); a never-touched view re-fits."""
        self.screen_w, self.screen_h = max(1, w), max(1, h)
        if self.auto_fit:
            self.fit()

    def one_to_one(self, scale: float = 1.0) -> None:
        """One game pixel per screen pixel x ``scale`` (the DPI factor), keeping the centre."""
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, scale))
        self.auto_fit = False

    def step_zoom_at(self, sx: float, sy: float, direction: int) -> None:
        """Wheel step: jump to the next crisp zoom level about a screen point."""
        target = zsnap.step(self.zoom, direction)
        self.zoom_at(sx, sy, target / self.zoom)

    def to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.cx) * self.zoom + self.screen_w / 2, (wy - self.cy) * self.zoom + self.screen_h / 2

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.screen_w / 2) / self.zoom + self.cx, (sy - self.screen_h / 2) / self.zoom + self.cy

    def pan(self, dsx: float, dsy: float) -> None:
        """Drag the map by a screen delta."""
        self.auto_fit = False
        self.cx -= dsx / self.zoom
        self.cy -= dsy / self.zoom
        self._clamp()

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Zoom about a screen point so the world point under it stays put."""
        self.auto_fit = False
        wx, wy = self.to_world(sx, sy)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self.cx = wx - (sx - self.screen_w / 2) / self.zoom
        self.cy = wy - (sy - self.screen_h / 2) / self.zoom
        self._clamp()

    def center_on(self, wx: float, wy: float) -> None:
        self.auto_fit = False
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
    from pokeagent.atlas.inplace import locate_in
    from pokeagent.atlas.world import CELL
    inside = locate_in(layout, wx / CELL, wy / CELL)
    if inside:
        return inside
    cx, cy = int(wx // CELL), int(wy // CELL)
    for m, p in layout.places.items():
        if m in layout.pins or m in layout.xf:
            continue
        if p.x <= cx < p.x + p.w and p.y <= cy < p.y + p.h:
            return m, cx - p.x, cy - p.y
    return None
