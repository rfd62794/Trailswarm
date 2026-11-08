"""The Dear PyGui window: one canvas of every area, all ghosts replayed over it via one texture.

Reused by import, unchanged, from ``pokeagent.world``: ``Viewport``, ``Pyramid``/``to_gpu``,
``Follow``. Every ghost head, trail and death mark is one RGBA array from ``overlay.render``
uploaded as ONE raw texture per frame, so display cost stays flat as ghosts grow.
"""
from __future__ import annotations

import time
from collections import OrderedDict

import dearpygui.dearpygui as dpg
import numpy as np

from pokeagent.mapview import overlay, playback
from pokeagent.mapview.best import best_index
from pokeagent.mapview.layout import LABEL_H, Layout
from pokeagent.world.follow import Follow
from pokeagent.world.pyramid import Pyramid, to_gpu
from pokeagent.world.view import Viewport

ROOT, TEX, CANVAS = "mapview_root", "mapview_tex", "mapview_canvas"
OVERLAY_TEX, AGENTS_PANE = "mapview_overlay_tex", "mapview_agents"
MAX_TEX, MAX_UPLOADS, COARSEST_F = 40, 2, 8   # chunk cache, uploads per frame, fallback depth
SPEEDS = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}


def compose_base(snap) -> np.ndarray | None:
    """The whole space as one RGB image: white background, each area's image at its offset."""
    w, h = snap.layout.space_w, snap.layout.space_h
    if not snap.areas or w <= 0 or h <= 0:
        return None
    img = np.full((h, w, 3), 255, np.uint8)
    for a in snap.areas:
        off, src = snap.layout.offsets.get(a.name), snap.images.get(a.name)
        if off is not None and src is not None:
            img[off[1]:off[1] + src.shape[0], off[0]:off[0] + src.shape[1]] = src[..., :3]
    return img


def agent_rows(tb: playback.Tables) -> list[tuple[str, int, int, str]]:
    """One summary row per distinct agent: (agent, palette slot, ghost count, furthest reached)."""
    by: dict[str, list] = {}
    for g in tb.ghosts:
        by.setdefault(g.agent, []).append(g)
    rows = []
    for agent in sorted(by):
        gs, b = by[agent], best_index(by[agent], tb.area_names)
        far = "-"
        if b is not None:
            r = int(gs[b].area_idx[-1])
            far = f"{tb.area_names[r] if 0 <= r < len(tb.area_names) else '?'} x{int(gs[b].xs[-1])}"
        rows.append((agent, overlay.color_index(agent, len(overlay.PALETTE)), len(gs), far))
    return rows


class MapWindow:
    """Window state plus one frame of work. ``headless`` skips input, textures and draw writes."""

    def __init__(self, snapshot, headless: bool = False, fps: int = playback.FPS) -> None:
        self.headless = headless
        self.clock, self.vp, self.follow = playback.Clock(), Viewport(1, 1), Follow()
        self.trails, self.marks, self.follow_best = True, True, False
        self.status, self.uploads, self.base_builds = "", 0, 0   # uploads/builds are test-visible
        self.base = self.pyr = self._snap = self._built_key = self._pending_tables = None
        self.tables = playback.tables((), (), fps)
        self.frame = playback.positions(self.tables, 0.0)
        self.layout, self.agent_rows, self.best = Layout({}, 0, 0), [], None
        self.overlay_img = np.zeros((1, 1, 4), np.uint8)
        self._tex, self._overlay_key, self._tex_uploads, self._fitted = OrderedDict(), None, 0, False
        self._down_at = self._last_mouse = self._follow_t = None
        self.adopt(snapshot)

    def adopt(self, snap) -> None:
        """Swap in the newest snapshot; recompose only on area/layout change; ghosts join at loop start."""
        if snap is self._snap:
            return
        self._snap = snap
        self.status = "" if snap.found else f"waiting for {snap.source}"
        key = (snap.layout, snap.areas)
        if key != self._built_key:
            self._built_key, self.layout = key, snap.layout
            self.base, self.base_builds = compose_base(snap), self.base_builds + 1
            self.pyr = Pyramid(self.base) if self.base is not None else None
            self._tex.clear()
            self.vp.world_w, self.vp.world_h = max(1, snap.layout.space_w), max(1, snap.layout.space_h)
            self.vp.cx = min(max(self.vp.cx, 0.0), float(self.vp.world_w))
            self.vp.cy = min(max(self.vp.cy, 0.0), float(self.vp.world_h))
            if not self._fitted and self.base is not None:
                self._fitted = True
                self.vp.fit()
        self._pending_tables = snap.tables
        if not self.tables.ghosts:
            self._use_pending()

    def _use_pending(self) -> None:
        if self._pending_tables is None: return
        self.tables, self._pending_tables = self._pending_tables, None
        self.clock.duration = float(self.tables.durations.max()) if len(self.tables.durations) else 0.0
        self.agent_rows = agent_rows(self.tables)
        if not self.headless:
            self._fill_agent_table()

    def build(self, parent=None) -> None:
        if not dpg.does_item_exist(TEX): dpg.add_texture_registry(tag=TEX, show=False)
        if parent is None:
            parent = dpg.add_window(tag=ROOT, label="Map view", no_scrollbar=True)
        cb = lambda f: (lambda s, a, u=None: f(a))
        with dpg.child_window(parent=parent, border=False, no_scrollbar=True):
            with dpg.group(horizontal=True):
                dpg.add_button(label="Pause", callback=cb(lambda a: self._toggle_pause()))
                dpg.add_combo(tuple(SPEEDS), default_value="1x", width=70,
                              callback=cb(lambda a: setattr(self.clock, "speed", SPEEDS.get(a, 1.0))))
                dpg.add_button(label="Fit", callback=cb(lambda a: self.vp.fit()))
                dpg.add_button(label="1:1", callback=cb(lambda a: self.vp.one_to_one()))
                for label, attr in (("trails", "trails"), ("marks", "marks")):
                    dpg.add_checkbox(label=label, default_value=True,
                                     callback=cb(lambda a, attr=attr: setattr(self, attr, bool(a))))
                dpg.add_checkbox(label="follow best", default_value=False,
                                 callback=cb(lambda a: self._set_follow_best(bool(a))))
            with dpg.group(horizontal=True):
                dpg.add_drawlist(width=800, height=560, tag=CANVAS)
                dpg.add_child_window(width=230, border=True, tag=AGENTS_PANE)
        if self.headless: return
        with dpg.handler_registry(tag="mapview_input"):
            dpg.add_mouse_wheel_handler(callback=cb(self._wheel))
            dpg.add_mouse_click_handler(dpg.mvMouseButton_Left, callback=lambda s, a, u=None: self._press())
            dpg.add_mouse_release_handler(dpg.mvMouseButton_Left, callback=lambda s, a, u=None: self._release())
        self._fill_agent_table()

    def _fill_agent_table(self) -> None:
        if not dpg.does_item_exist(AGENTS_PANE): return
        dpg.delete_item(AGENTS_PANE, children_only=True)
        for agent, cidx, n, far in self.agent_rows:
            with dpg.group(horizontal=True, parent=AGENTS_PANE):
                sw = dpg.add_drawlist(width=12, height=12)
                dpg.draw_rectangle((0, 0), (12, 12), parent=sw,
                                   fill=(*[int(c) for c in overlay.PALETTE[cidx]], 255))
                dpg.add_selectable(label=f"{agent}  x{n}  {far}",
                                   callback=lambda s, a, u, agent=agent: self._follow_agent(agent))

    def _toggle_pause(self) -> None: self.clock.paused = not self.clock.paused

    def _set_follow_best(self, on: bool) -> None:
        self.follow_best = on
        if not on: self.follow.stop()

    def _follow_agent(self, agent: str) -> None:
        gs = [g for g in self.tables.ghosts if g.agent == agent]
        if (b := best_index(gs, self.tables.area_names)) is not None:
            self._set_follow_best(False)
            self.follow.start(gs[b].run, time.monotonic())
            if (p := self._points().get(gs[b].run)) is not None:
                self.vp.center_on(*p)

    def resize(self, w: int, h: int) -> None:
        if not dpg.does_item_exist(CANVAS): return
        dpg.configure_item(CANVAS, width=max(100, w - 250), height=max(100, h - 60))
        self.vp.resize(max(100, w - 250), max(100, h - 60))

    def _mouse(self):
        if not dpg.does_item_exist(CANVAS) or not dpg.is_item_hovered(CANVAS):
            return None
        mx, my = dpg.get_mouse_pos(local=False)
        ox, oy = dpg.get_item_rect_min(CANVAS)
        return mx - ox, my - oy

    def _wheel(self, delta) -> None:
        if (m := self._mouse()) is not None:
            self.vp.step_zoom_at(m[0], m[1], 1 if float(delta) > 0 else -1)

    def _press(self) -> None: self._down_at = self._mouse()

    def _release(self) -> None: self._down_at = self._last_mouse = None

    def _drag(self) -> None:
        m = self._mouse()
        down = m is not None and self._down_at is not None and dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
        if down and self._last_mouse is not None:
            d = (m[0] - self._last_mouse[0], m[1] - self._last_mouse[1])
            if d[0] or d[1]:
                self.vp.pan(*d)
                self.follow.stop()
        self._last_mouse = m if down else None

    def tick(self, dt: float, now: float | None = None) -> playback.Frame:
        """One frame of replay: advance the shared clock, follow, rasterise the one overlay."""
        now = time.monotonic() if now is None else now
        if self.clock.advance(dt) or not self.tables.ghosts:
            self._use_pending()
        self.frame = playback.positions(self.tables, self.clock.t)
        self.best = best_index(self.tables.ghosts, self.tables.area_names)
        self._follow_tick(now, dt)
        self.overlay_img = overlay.render(self.frame, self.tables, self.layout, self.vp.visible(),
                                          self.vp.zoom, trails=self.trails,
                                          show_marks=self.marks, best=self.best)
        self.uploads += 1
        if not self.headless:
            self._upload_overlay()
            self._draw()
        return self.frame

    def _points(self) -> dict[str, tuple[float, float]]:
        pts = {}
        for k, g in enumerate(self.tables.ghosts):
            a = int(self.frame.area[k])
            if 0 <= a < len(self.tables.area_names):
                off = self.layout.offsets.get(self.tables.area_names[a])
                if off is not None:
                    pts[g.run] = (off[0] + float(self.frame.xs[k]), off[1] + float(self.frame.ys[k]))
        return pts

    def _follow_tick(self, now: float, dt: float) -> None:
        if self.follow_best and self.best is not None:
            run = self.tables.runs[self.best]
            if run != self.follow.agent_id:
                self.follow.start(run, now)
        target = self.follow.target(self._points(), now)
        if target is not None:
            self.follow.step(self.vp, target, 0.0 if self._follow_t is None else now - self._follow_t)
        self._follow_t = now

    def _upload_overlay(self) -> None:
        h, w = self.overlay_img.shape[:2]
        if self._overlay_key != (w, h):
            if dpg.does_item_exist(OVERLAY_TEX):
                dpg.delete_item(OVERLAY_TEX)
            self._overlay_key = (w, h)
            dpg.add_raw_texture(w, h, np.zeros(w * h * 4, np.float32),
                                format=dpg.mvFormat_Float_rgba, tag=OVERLAY_TEX, parent=TEX)
        dpg.set_value(OVERLAY_TEX, self.overlay_img.astype(np.float32).ravel() / 255.0)

    def _chunk_tex(self, f: int, cx: int, cy: int):
        key = (id(self.pyr), f, cx, cy)
        if key in self._tex:
            self._tex.move_to_end(key)
            return self._tex[key]
        if self._tex_uploads >= MAX_UPLOADS: return None
        self._tex_uploads += 1
        rgb = self.pyr.chunk(f, cx, cy)
        tag = dpg.add_static_texture(rgb.shape[1], rgb.shape[0], to_gpu(rgb), parent=TEX)
        self._tex[key] = tag
        while len(self._tex) > MAX_TEX:
            dpg.delete_item(self._tex.popitem(last=False)[1])
        return tag

    def _draw(self) -> None:
        if not dpg.does_item_exist(CANVAS): return
        self._drag()
        dpg.delete_item(CANVAS, children_only=True)
        if self.pyr is None:
            dpg.draw_text((20, 20), self.status or "no areas yet", size=18, parent=CANVAS)
            return
        vp, self._tex_uploads = self.vp, 0
        f, chunks = self.pyr.plan(vp.zoom, vp.visible(), MAX_TEX - 10)
        for cx, cy in chunks:
            if (tex := self._chunk_tex(f, cx, cy)) is not None:
                x0, y0, x1, y1 = self.pyr.chunk_rect(f, cx, cy)
                dpg.draw_image(tex, vp.to_screen(x0, y0), vp.to_screen(x1, y1), parent=CANVAS)
            else:
                self._draw_coarser(f, cx, cy)
        dpg.draw_image(OVERLAY_TEX, (0, 0), self.overlay_img.shape[:2][::-1], parent=CANVAS)
        seen = {a.name: a.seen for a in self._snap.areas}
        for name, (ax, ay) in self.layout.offsets.items():
            dpg.draw_text(vp.to_screen(ax, ay - LABEL_H + 2), f"{name} {seen.get(name, 0.0):.0%}",
                          size=14, parent=CANVAS)
        if self.follow.active:
            dpg.draw_text((12, 8), f"following {self.follow.agent_id}", size=14, parent=CANVAS)

    def _draw_coarser(self, f: int, cx: int, cy: int) -> None:
        g = f * 2
        while g <= COARSEST_F:
            pcx, pcy, u0, v0, u1, v1 = self.pyr.parent(f, cx, cy, g)
            if (tex := self._chunk_tex(g, pcx, pcy)) is not None:
                x0, y0, x1, y1 = self.pyr.chunk_rect(f, cx, cy)
                dpg.draw_image(tex, self.vp.to_screen(x0, y0), self.vp.to_screen(x1, y1),
                               uv_min=(u0, v0), uv_max=(u1, v1), parent=CANVAS)
                return
            g *= 2
