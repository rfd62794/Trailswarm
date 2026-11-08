"""Rasterise all ghosts, trails, death marks, avatars and the live agent into ONE RGBA array.

Pure numpy: heads, trail points and marks are written into the output array by fancy indexing,
so display cost does not depend on how many ghosts are shown - the view uploads this one array
as one texture per frame; there are no per-ghost items, and avatars composite only heads
inside the visible rectangle."""
from __future__ import annotations

import math
import zlib

import numpy as np

from pokeagent.mapview.playback import TRAIL_POINTS, Frame, Tables

MAX_TRAIL_PIXELS = 20000   # trail points per frame; beyond this, trails are decimated evenly
DEATH_OUTCOMES = frozenset({"death", "dead", "died", "fail"})
PALETTE = np.array([(232, 76, 61), (52, 128, 235), (46, 178, 90), (240, 178, 41),
                    (155, 89, 224), (38, 184, 190), (233, 116, 171), (150, 105, 60)], np.uint8)
BEST_RGB, BEST_EDGE = np.array([255, 255, 255], np.uint8), np.array([25, 25, 25], np.uint8)
MARK_RGB = np.array([225, 45, 45], np.uint8)


def color_index(agent: str, n: int) -> int:
    """A stable palette slot from the agent string (crc32, so it is the same every run)."""
    return zlib.crc32(agent.encode("utf-8")) % n


def _offsets(tb: Tables, layout) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """area index -> space offset; ``known`` masks names the layout has not captured yet."""
    ox, oy, known = np.zeros(size := len(tb.area_names)), np.zeros(size), np.zeros(size, bool)
    for k, name in enumerate(tb.area_names):
        o = layout.offsets.get(name)
        if o is not None:
            known[k], ox[k], oy[k] = True, o[0], o[1]
    return ox, oy, known


def _square(out: np.ndarray, cx: float, cy: float, side: int, rgb: np.ndarray) -> None:
    h, w = out.shape[:2]
    if not (math.isfinite(cx) and math.isfinite(cy)):
        return
    cxi, cyi, r = int(round(cx)), int(round(cy)), side // 2
    xa, xb, ya, yb = max(0, cxi - r), min(w, cxi + r + 1), max(0, cyi - r), min(h, cyi + r + 1)
    if xa < xb and ya < yb: out[ya:yb, xa:xb, :3], out[ya:yb, xa:xb, 3] = rgb, 255


def _ring(out: np.ndarray, cx: float, cy: float, w: int, h: int, rgb: np.ndarray) -> None:
    """A hollow 1 px border around the w x h box centred at (cx, cy), clipped to `out`."""
    H, W, x0, y0 = *out.shape[:2], int(round(cx - w / 2)), int(round(cy - h / 2))
    for ya, yb, xa, xb in ((y0, y0 + 1, x0, x0 + w), (y0 + h - 1, y0 + h, x0, x0 + w),
                           (y0 + 1, y0 + h - 1, x0, x0 + 1), (y0 + 1, y0 + h - 1, x0 + w - 1, x0 + w)):
        ya, yb, xa, xb = max(0, ya), min(H, yb), max(0, xa), min(W, xb)
        if ya < yb and xa < xb:
            out[ya:yb, xa:xb, :3], out[ya:yb, xa:xb, 3] = rgb, 255


def _zoom_img(img: np.ndarray, zoom: float, size: int) -> np.ndarray:
    """Nearest-neighbour resample (index repeat) so the longest side lands near size*zoom."""
    k = max(1e-9, size * zoom / max(1, max(img.shape[:2])))
    h, w = (max(1, int(round(d * k))) for d in img.shape[:2])
    if (h, w) == tuple(img.shape[:2]):
        return img
    yi, xi = (np.arange(h) * img.shape[0] // h), (np.arange(w) * img.shape[1] // w)
    return img[np.ix_(yi, xi)]


def _stamp(out: np.ndarray, img: np.ndarray, cx: float, cy: float) -> None:
    """Alpha-composite ``img`` centred on (cx, cy), clipped to the output rectangle."""
    h, w, ih, iw = *out.shape[:2], *img.shape[:2]
    x0, y0 = int(round(cx - iw / 2)), int(round(cy - ih / 2))
    xa, xb, ya, yb = max(0, x0), min(w, x0 + iw), max(0, y0), min(h, y0 + ih)
    if xa >= xb or ya >= yb:
        return
    sub, reg = img[ya - y0:yb - y0, xa - x0:xb - x0], out[ya:yb, xa:xb]
    f = sub[..., 3:4].astype(np.float32) / 255.0
    reg[..., :3] = (sub[..., :3] * f + reg[..., :3] * (1 - f)).astype(np.uint8)
    reg[..., 3] = np.maximum(reg[..., 3], sub[..., 3])


def _stamp_all(out, img, xs0, ys0) -> None:
    """One binary-alpha image stamped at every (xs0, ys0) top-left in one fancy-indexed write."""
    th, tw = img.shape[:2]
    py, px = (np.broadcast_to(ys0[:, None, None] + np.arange(th)[None, :, None], (len(xs0), th, tw)).ravel(),
              np.broadcast_to(xs0[:, None, None] + np.arange(tw)[None, None, :], (len(xs0), th, tw)).ravel())
    di = np.tile((np.arange(th)[:, None] * tw + np.arange(tw)[None, :]).ravel(), len(xs0))
    inside = (px >= 0) & (px < out.shape[1]) & (py >= 0) & (py < out.shape[0]) & (img[..., 3].ravel()[di] > 0)
    out[py[inside], px[inside], :3] = img[..., :3].reshape(-1, 3)[di[inside]]
    out[py[inside], px[inside], 3] = 255


def _live(out, live, avatars, size, zoom, x0, y0, side, palette) -> None:
    """Each live agent (space coords) drawn like a head plus a 1 px white ring."""
    for agent, lx, ly, f, ph in live:
        px, py = (lx - x0) * zoom, (ly - y0) * zoom
        if not (0 <= px < out.shape[1] and 0 <= py < out.shape[0] and math.isfinite(px) and math.isfinite(py)):
            continue
        rgb = palette[color_index(agent, len(palette))]
        img = None if avatars is None else avatars.get(agent, f, ph, tuple(int(c) for c in rgb))
        if img is None:
            _square(out, px, py, side, rgb)
            rw = rh = side + 2
        else:
            s = _zoom_img(img, zoom, size)
            _stamp(out, s, px, py)
            rw, rh = s.shape[1] + 2, s.shape[0] + 2
        _ring(out, px, py, rw, rh, BEST_RGB)


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
    raw = tb.area_idx[gid, jj].astype(np.intp)
    aa = np.clip(raw, 0, len(known) - 1)
    px = (ox[aa] + tb.xs[gid, jj] - x0) * zoom
    py = (oy[aa] + tb.ys[gid, jj] - y0) * zoom
    inside = (raw >= 0) & (raw < len(known)) & known[aa] & (px >= 0) & (px < w) & (py >= 0) & (py < h)
    gi, xi, yi = gid[inside], px[inside].astype(np.intp), py[inside].astype(np.intp)
    age = (np.repeat(frame.idx, keep)[inside] - jj[inside]) / float(TRAIL_POINTS)
    out[yi, xi, :3] = colors[gi]
    out[yi, xi, 3] = np.clip(235 - 175 * np.minimum(age, 1.0), 60, 235).astype(np.uint8)


def render(frame: Frame, tb: Tables, layout, rect, zoom, palette: np.ndarray = PALETTE, *,
           trails: bool = True, show_marks: bool = True, best: int | None = None,
           avatars=None, avatar_size: int = 16, live=None, walk_frames: bool = False) -> np.ndarray:
    """ONE uint8 RGBA array the size of the visible screen rectangle (never the whole space).
    ``avatars``: object with ``get(agent, facing, phase, colour) -> RGBA | None``; ``live``:
    ``(agent, x, y, facing, phase)`` tuples in space coordinates."""
    x0, y0, x1, y1 = rect
    w, h = max(1, int(round((x1 - x0) * zoom))), max(1, int(round((y1 - y0) * zoom)))
    out, side = np.zeros((h, w, 4), np.uint8), max(3, int(3 * zoom))
    if (count := len(tb.ghosts)) and tb.area_names:
        ox, oy, known = _offsets(tb, layout)
        if known.any():
            colors = np.stack([palette[color_index(a, len(palette))] for a in tb.agents])
            if trails: _trails(out, frame, tb, ox, oy, known, colors, x0, y0, zoom, w, h)
            ai = np.clip(frame.area.astype(np.intp), 0, len(known) - 1)
            ok = (frame.area >= 0) & (frame.area < len(known)) & known[ai]
            hx, hy = (ox[ai] + frame.xs - x0) * zoom, (oy[ai] + frame.ys - y0) * zoom
            sel, have = np.array([k for k in range(count) if k != best and ok[k]], np.intp), np.zeros(count, bool)
            if avatars is not None:
                ct, groups = [tuple(int(c) for c in colors[k]) for k in range(count)], {}
                pi, gi = np.clip(frame.idx.astype(np.intp) - 1, 0, None), np.arange(count)
                ok_prev = (frame.idx > 0) & (tb.area_idx[gi, pi] == frame.area)
                dx, dy = (np.where(ok_prev, frame.xs - tb.xs[gi, pi], 0.0),
                          np.where(ok_prev, frame.ys - tb.ys[gi, pi], 0.0))
                moved = (dx != 0) | (dy != 0)
                facs = np.where(dx >= 0, "RIGHT", "LEFT")
                phs = np.zeros(count, np.intp)
                if walk_frames:
                    facs = np.where(moved, np.where(np.abs(dx) >= np.abs(dy), facs,
                                    np.where(dy >= 0, "DOWN", "UP")), "DOWN")
                    phs = np.where(moved, frame.idx // 6 % 2 + 1, 0)
                got = {}
                for k in sel:
                    if not (0 <= hx[k] < w and 0 <= hy[k] < h):
                        continue                        # only heads inside the rectangle
                    key = (tb.agents[k], facs[k], int(phs[k]))
                    if key not in got:
                        got[key] = avatars.get(tb.agents[k], facs[k], int(phs[k]), ct[k])
                    if (img := got[key]) is not None:
                        have[k] = True
                        groups.setdefault(id(img), (img, []))[1].append(k)
                for img, ks in groups.values():         # resample once per picture
                    s = _zoom_img(img, zoom, avatar_size)
                    if ((s[..., 3] > 0) & (s[..., 3] < 255)).any():
                        for k in ks:                    # partial alpha: blend per head
                            _stamp(out, s, hx[k], hy[k])
                    else:
                        _stamp_all(out, s, np.round(hx[ks] - s.shape[1] / 2).astype(np.intp),
                                   np.round(hy[ks] - s.shape[0] / 2).astype(np.intp))
            if len(sq := sel[~have[sel]]):
                r = np.arange(side) - side // 2
                px = np.broadcast_to(np.round(hx[sq]).astype(np.intp)[:, None, None] + r[None, :, None],
                                     (len(sq), side, side)).ravel()
                py = np.broadcast_to(np.round(hy[sq]).astype(np.intp)[:, None, None] + r[None, None, :],
                                     (len(sq), side, side)).ravel()
                inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
                out[py[inside], px[inside], :3] = np.repeat(colors[sq], side * side, axis=0)[inside]
                out[py[inside], px[inside], 3] = 255
            if best is not None and 0 <= best < count and ok[best]:
                _square(out, hx[best], hy[best], side + 2, BEST_EDGE)
                _square(out, hx[best], hy[best], side, BEST_RGB)
            if show_marks:
                dead = frame.finished & np.array([o in DEATH_OUTCOMES for o in tb.outcomes]) & ok
                cx, cy = np.round(hx[dead]).astype(np.intp), np.round(hy[dead]).astype(np.intp)
                arms, span = np.array([-2, -1, 0, 1, 2, 0, 0, 0, 0]), np.array([0, 0, 0, 0, 0, -2, -1, 1, 2])
                mx, my = (cx[:, None] + arms).ravel(), (cy[:, None] + span).ravel()
                inside = (mx >= 0) & (mx < w) & (my >= 0) & (my < h)
                out[my[inside], mx[inside], :3], out[my[inside], mx[inside], 3] = MARK_RGB, 255
    _live(out, live or (), avatars, avatar_size, zoom, x0, y0, side, palette)
    return out
