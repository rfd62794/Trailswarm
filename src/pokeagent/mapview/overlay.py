"""Rasterise all ghosts, trails and death marks into ONE RGBA array for the visible rectangle.

Pure numpy: heads, trail points and marks are written into the output array by fancy indexing,
so display cost does not depend on how many ghosts are shown - the view uploads this one array
as one texture per frame; there are no per-ghost items. Points outside the visible rectangle
are discarded by masks before rasterising.
"""
from __future__ import annotations

import zlib

import numpy as np

from pokeagent.mapview.playback import TRAIL_POINTS, Frame, Tables

MAX_TRAIL_PIXELS = 20000   # trail points per frame; beyond this, trails are decimated evenly
DEATH_OUTCOMES = frozenset({"death", "dead", "died", "fail"})
PALETTE = np.array([(232, 76, 61), (52, 128, 235), (46, 178, 90), (240, 178, 41),
                    (155, 89, 224), (38, 184, 190), (233, 116, 171), (150, 105, 60)], np.uint8)
BEST_RGB = np.array([255, 255, 255], np.uint8)
BEST_EDGE = np.array([25, 25, 25], np.uint8)
MARK_RGB = np.array([225, 45, 45], np.uint8)


def color_index(agent: str, n: int) -> int:
    """A stable palette slot from the agent string (crc32, so it is the same every run)."""
    return zlib.crc32(agent.encode("utf-8")) % n


def _offsets(tb: Tables, layout) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """area index -> space offset; ``known`` masks names the layout has not captured yet."""
    size = len(tb.area_names)
    ox, oy, known = np.zeros(size), np.zeros(size), np.zeros(size, bool)
    for k, name in enumerate(tb.area_names):
        o = layout.offsets.get(name)
        if o is not None:
            known[k], ox[k], oy[k] = True, o[0], o[1]
    return ox, oy, known


def _square(out: np.ndarray, cx: float, cy: float, side: int, rgb: np.ndarray) -> None:
    h, w = out.shape[:2]
    cxi, cyi, r = int(round(cx)), int(round(cy)), side // 2
    xa, xb, ya, yb = max(0, cxi - r), min(w, cxi + r + 1), max(0, cyi - r), min(h, cyi + r + 1)
    if xa < xb and ya < yb:
        out[ya:yb, xa:xb, :3], out[ya:yb, xa:xb, 3] = rgb, 255


def _trails(out, frame: Frame, tb: Tables, ox, oy, known, colors, x0, y0, zoom, w, h) -> None:
    count = len(tb.ghosts)
    stride = max(1, (count * TRAIL_POINTS + MAX_TRAIL_PIXELS - 1) // MAX_TRAIL_PIXELS)
    keep = np.clip((frame.idx - frame.trail_from) // stride + 1, 0, None)
    total = int(keep.sum())
    if total == 0:
        return
    gid = np.repeat(np.arange(count), keep)
    kth = np.arange(total) - np.repeat(np.cumsum(keep) - keep, keep)
    jj = np.repeat(frame.idx, keep) - kth * stride       # newest first: stride-decimated back
    aa = np.clip(tb.area_idx[gid, jj].astype(np.intp), 0, None)
    px = (ox[aa] + tb.xs[gid, jj] - x0) * zoom
    py = (oy[aa] + tb.ys[gid, jj] - y0) * zoom
    inside = (tb.area_idx[gid, jj] >= 0) & known[aa] & (px >= 0) & (px < w) & (py >= 0) & (py < h)
    gi, xi, yi = gid[inside], px[inside].astype(np.intp), py[inside].astype(np.intp)
    age = (np.repeat(frame.idx, keep)[inside] - jj[inside]) / float(TRAIL_POINTS)
    out[yi, xi, :3] = colors[gi]
    out[yi, xi, 3] = np.clip(235 - 175 * np.minimum(age, 1.0), 60, 235).astype(np.uint8)


def render(frame: Frame, tb: Tables, layout, rect, zoom, palette: np.ndarray = PALETTE, *,
           trails: bool = True, show_marks: bool = True, best: int | None = None) -> np.ndarray:
    """ONE uint8 RGBA array the size of the visible screen rectangle (never the whole space)."""
    x0, y0, x1, y1 = rect
    w, h = max(1, int(round((x1 - x0) * zoom))), max(1, int(round((y1 - y0) * zoom)))
    out = np.zeros((h, w, 4), np.uint8)
    count = len(tb.ghosts)
    if count == 0:
        return out
    ox, oy, known = _offsets(tb, layout)
    colors = np.stack([palette[color_index(a, len(palette))] for a in tb.agents])
    if trails:
        _trails(out, frame, tb, ox, oy, known, colors, x0, y0, zoom, w, h)
    ai = np.clip(frame.area.astype(np.intp), 0, None)
    ok = (frame.area >= 0) & known[ai]
    hx = (ox[ai] + frame.xs - x0) * zoom
    hy = (oy[ai] + frame.ys - y0) * zoom
    side = max(3, int(3 * zoom))
    sel = np.array([k for k in range(count) if k != best and ok[k]], np.intp)
    if len(sel):
        r = np.arange(side) - side // 2
        px = np.broadcast_to(np.round(hx[sel]).astype(np.intp)[:, None, None] + r[None, :, None],
                             (len(sel), side, side)).ravel()
        py = np.broadcast_to(np.round(hy[sel]).astype(np.intp)[:, None, None] + r[None, None, :],
                             (len(sel), side, side)).ravel()
        inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        out[py[inside], px[inside], :3] = np.repeat(colors[sel], side * side, axis=0)[inside]
        out[py[inside], px[inside], 3] = 255
    if best is not None and 0 <= best < count and ok[best]:
        _square(out, hx[best], hy[best], side + 2, BEST_EDGE)
        _square(out, hx[best], hy[best], side, BEST_RGB)
    if show_marks:
        dead = frame.finished & np.array([o in DEATH_OUTCOMES for o in tb.outcomes]) & ok
        cx, cy = np.round(hx[dead]).astype(np.intp), np.round(hy[dead]).astype(np.intp)
        arms = np.array([-2, -1, 0, 1, 2, 0, 0, 0, 0])
        span = np.array([0, 0, 0, 0, 0, -2, -1, 1, 2])
        mx, my = (cx[:, None] + arms).ravel(), (cy[:, None] + span).ravel()
        inside = (mx >= 0) & (mx < w) & (my >= 0) & (my < h)
        out[my[inside], mx[inside], :3] = MARK_RGB
        out[my[inside], mx[inside], 3] = 255
    return out
