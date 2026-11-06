"""World mode: the stitched Kanto as chunked textures with zoom/pan, every agent drawn live over it.

All Dear PyGui calls for the map live here (side panel: ``world_side``). Heavy work (ROM render, layer composition) runs on a
worker thread; the render loop only draws what is ready. Hit testing and zoom maths are pure (``pokeagent.world.view``).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

import dearpygui.dearpygui as dpg
import numpy as np

from pokeagent.atlas import sprites
from pokeagent.world import anim, draw
from pokeagent.world.pyramid import LEVELS, Pyramid, to_gpu
from pokeagent.world.view import Viewport, locate, pick

TEX = "world_tex"
MAX_UPLOADS = 2         # chunk uploads per frame (a pan never stalls the UI on a burst of 16 MB uploads)
MAX_TEX = 40            # chunk textures kept on the GPU (about 16 MB each)
MIN_SPRITE_PX = 26      # an agent is never drawn smaller than this, however far out you zoom
REBUILD_S = 3.0         # layer images are recomposed at most this often


class WorldView:
    def __init__(self, parent, world_model, on_focus, on_select, loader, side_cls=None) -> None:
        self.wm, self._on_focus, self._on_select = world_model, on_focus, on_select
        self.world = None                      # world.export.World once loaded
        self.pyr: Pyramid | None = None
        self.vp = Viewport(1000, 1000)
        self.layers: set[str] = set()
        self.trails = True
        self.npcs = False
        self.hover_text: list[str] = []
        self.status = "loading Kanto from the ROM..."
        self._tex: OrderedDict = OrderedDict()
        self._sprite_tex: dict = {}
        self._last_mouse: tuple[float, float] | None = None
        self._down_at: tuple[float, float] | None = None
        self._pending: Pyramid | None = None
        self._loaded = None
        self._uploads = 0
        self._built_for: tuple | None = None
        self._building = False
        self._built_at = 0.0
        self._points: dict[str, tuple[float, float]] = {}
        if not dpg.does_item_exist(TEX):
            dpg.add_texture_registry(tag=TEX, show=False)
        self.area = dpg.add_child_window(parent=parent, width=10, height=10, border=False, no_scrollbar=True, tag="world_area",
                                         show=False)
        with dpg.group(horizontal=True, parent=self.area):
            self.canvas = dpg.add_drawlist(width=800, height=600, tag="world_canvas")
            self.side = side_cls(self) if side_cls else None
        with dpg.handler_registry(tag="world_input"):
            dpg.add_mouse_wheel_handler(callback=lambda s, a, u: self._wheel(a))
            dpg.add_mouse_click_handler(dpg.mvMouseButton_Left, callback=lambda *_: self._click())
            dpg.add_mouse_double_click_handler(dpg.mvMouseButton_Left, callback=lambda *_: self._double())
            dpg.add_mouse_release_handler(dpg.mvMouseButton_Left, callback=lambda *_: self._release())
        self._loader, self._started = loader, False

    # -- loading / layer composition (worker threads) ------------------------------------
    def _load(self, loader) -> None:
        try:
            w = loader()
            pyr = Pyramid(w.base)
            for f in (2, 4, 8):
                pyr.level(f)
            self._loaded = (w, pyr)                 # the UI thread adopts it (viewport state is never touched from here)
        except Exception as exc:
            self.status = f"world failed to load: {exc}"

    def _want(self) -> tuple:
        maps = frozenset(t.map for t in self.wm.tracks() if t.placed) if self.npcs else frozenset()
        return (frozenset(self.layers), maps, self.wm.rev if self.layers else 0)

    def _maybe_rebuild(self, now: float) -> None:
        want = self._want()
        if self.world is None or self._building or want == self._built_for or now - self._built_at < REBUILD_S:
            return
        self._building, self._built_at = True, now

        def work() -> None:
            try:
                w = self.world
                if not want[0] and not want[1]:
                    img = w.base
                else:
                    img = draw.compose_layers(w.base, w.layout, self.wm.union_model(), w.headers, tuple(sorted(want[0])),
                                              w.book if want[1] else None, set(want[1]))
                p = Pyramid(img)
                for f in (2, 4, 8):
                    p.level(f)
                self._pending, self._built_for = p, want
            finally:
                self._building = False
        threading.Thread(target=work, daemon=True, name="world-layers").start()

    # -- textures ------------------------------------------------------------------------
    def _chunk_tex(self, f: int, cx: int, cy: int, force: bool = False):
        """The texture of a chunk if it is on the GPU; otherwise upload it - at most MAX_UPLOADS per frame (None = not yet)."""
        key = (id(self.pyr), f, cx, cy)
        if key in self._tex:
            self._tex.move_to_end(key)
            return self._tex[key]
        if self._uploads >= MAX_UPLOADS and not force:
            return None
        self._uploads += 1
        rgb = self.pyr.chunk(f, cx, cy)
        tag = dpg.add_static_texture(rgb.shape[1], rgb.shape[0], to_gpu(rgb), parent=TEX)
        self._tex[key] = tag
        while len(self._tex) > MAX_TEX:
            _, old = self._tex.popitem(last=False)
            dpg.delete_item(old)
        return tag

    def _agent_tex(self, facing: str, phase: int, colour):
        key = (facing, phase, colour)
        if key not in self._sprite_tex:
            img = self.world.book.image(sprites.PLAYER, facing, phase, colour)
            self._sprite_tex[key] = dpg.add_static_texture(18, 18, to_gpu_rgba(np.asarray(img)), parent=TEX)
        return self._sprite_tex[key]

    # -- input ---------------------------------------------------------------------------
    def _mouse(self) -> tuple[float, float] | None:
        """Mouse position in canvas pixels when it is over the canvas, else None."""
        if not dpg.does_item_exist(self.canvas) or not dpg.is_item_hovered(self.canvas):
            return None
        mx, my = dpg.get_mouse_pos(local=False)
        ox, oy = dpg.get_item_rect_min(self.canvas)
        return mx - ox, my - oy

    def _wheel(self, delta) -> None:
        m = self._mouse()
        if m and self.pyr:
            self.vp.zoom_at(m[0], m[1], 1.15 ** float(delta))

    def _click(self) -> None:
        self._down_at = self._mouse()

    def _release(self) -> None:
        m, d = self._mouse(), self._down_at
        self._down_at = self._last_mouse = None
        if m and d and abs(m[0] - d[0]) < 4 and abs(m[1] - d[1]) < 4 and self.world:
            aid = pick(self._points, self.vp, *m)
            if aid:
                self._on_select(aid)
            elif self.side:
                loc = locate(self.world.layout, *self.vp.to_world(*m))
                if loc:
                    self.side.show_tile(*loc)

    def _double(self) -> None:
        m = self._mouse()
        aid = pick(self._points, self.vp, *m) if m else None
        if aid:
            self._on_focus(aid)

    def _drag(self) -> None:
        m = self._mouse()
        if m and dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            if self._last_mouse:
                self.vp.pan(m[0] - self._last_mouse[0], m[1] - self._last_mouse[1])
            self._last_mouse = m
        else:
            self._last_mouse = None

    # -- per frame -----------------------------------------------------------------------
    def fit(self, w: int, h: int) -> None:
        """Size the area to the viewport (the canvas takes what the side panel leaves)."""
        side_w = self.side.width if self.side else 0
        dpg.configure_item(self.area, width=w - 8, height=h)
        cw, ch = max(100, w - side_w - 24), max(100, h - 8)
        dpg.configure_item(self.canvas, width=cw, height=ch)
        self.vp.resize(cw, ch)
        if self.side:
            self.side.fit(h)

    def update(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        dl = self.canvas
        if not self._started:       # the ROM render starts the first time world mode is shown
            self._started = True
            threading.Thread(target=self._load, args=(self._loader,), daemon=True, name="world-load").start()
        dpg.delete_item(dl, children_only=True)
        if self._loaded is not None:
            (self.world, self.pyr), self._loaded = self._loaded, None
            self.vp = Viewport(*self.world.layout.size_px, self.vp.screen_w, self.vp.screen_h)
            self.vp.fit()
            self.status = ""
        if self.pyr is None:
            dpg.draw_text((20, 20), self.status, size=18, parent=dl)
            return
        if self._pending is not None:
            self.pyr, self._pending = self._pending, None
        self._maybe_rebuild(now)
        self._drag()
        vp, self._uploads = self.vp, 0
        f, chunks = self.pyr.plan(vp.zoom, vp.visible(), MAX_TEX - 10)
        for cx, cy in chunks:
            x0, y0, x1, y1 = self.pyr.chunk_rect(f, cx, cy)
            a, b = vp.to_screen(x0, y0), vp.to_screen(x1, y1)
            tex = self._chunk_tex(f, cx, cy)
            if tex is not None:
                dpg.draw_image(tex, a, b, parent=dl)
            else:
                self._draw_coarser(f, cx, cy, a, b)
        self._draw_agents(now)
        self._draw_hover()
        if self.side:
            self.side.update()

    def _draw_coarser(self, f: int, cx: int, cy: int, a, b) -> None:
        """Until the sharp chunk is uploaded show the same area from a coarser level (the coarsest is tiny, always affordable)."""
        g = f * 2
        while g <= LEVELS[-1]:
            pcx, pcy, u0, v0, u1, v1 = self.pyr.parent(f, cx, cy, g)
            tex = self._chunk_tex(g, pcx, pcy, force=g == LEVELS[-1])
            if tex is not None:
                dpg.draw_image(tex, a, b, uv_min=(u0, v0), uv_max=(u1, v1), parent=self.canvas)
                return
            g *= 2

    def _draw_agents(self, now: float) -> None:
        w, vp, dl = self.world, self.vp, self.canvas
        tracks = self.wm.tracks()
        ids = [t.id for t in tracks]
        self._points = {}
        for t in tracks:
            col = draw.agent_colour(t.id, ids)
            if self.trails:
                pts = [vp.to_screen(*p) for p in anim.trail_points(t, w.layout, 120)]
                n = len(pts)
                for a in range(0, n - 1, 8):
                    dpg.draw_polyline(pts[a:a + 9], color=(*col, 60 + 180 * a // max(n, 1)), thickness=2, parent=dl)
            pos = anim.place(t, w.layout, now)
            if pos is None:
                continue
            x, y, phase = pos
            cx, cy = vp.to_screen(x + 8, y + 8)
            self._points[t.id] = (x + 8, y + 8)
            half = max(9 * vp.zoom, MIN_SPRITE_PX / 2)
            dpg.draw_circle((cx, cy), half + 3, color=(*col, 255), thickness=2, parent=dl)
            dpg.draw_image(self._agent_tex(t.facing, phase, col), (cx - half, cy - half), (cx + half, cy + half), parent=dl)
            dpg.draw_text((cx + half + 4, cy - 8), t.id[-8:], color=(255, 255, 255, 255), size=14, parent=dl)
            if t.battle and t.battle.ended_at is None:
                for a, b in (((-7, -34), (7, -20)), ((7, -34), (-7, -20))):
                    dpg.draw_line((cx + a[0], cy + a[1]), (cx + b[0], cy + b[1]), color=(230, 40, 40, 255), thickness=3, parent=dl)
                dpg.draw_text((cx - 24, cy - 52), t.battle.species or "?", color=(255, 220, 80, 255), size=14, parent=dl)

    def _draw_hover(self) -> None:
        m = self._mouse()
        if not m:
            return
        aid = pick(self._points, self.vp, *m)
        if aid:
            t = self.wm.track(aid)
            lines = [aid, f"step {t.step}  goal: {t.goal or '-'}", "in battle" if t.battle and not t.battle.ended_at else ""]
        else:
            loc = locate(self.world.layout, *self.vp.to_world(*m))
            lines = [f"{loc}"] if loc else []
        lines = [s for s in lines if s]
        for i, s in enumerate(lines):
            dpg.draw_text((m[0] + 14, m[1] + 8 + 15 * i), s, color=(255, 255, 160, 255), size=14, parent=self.canvas)

    def delete(self) -> None:
        for t in (self.area, "world_input"):
            if dpg.does_item_exist(t):
                dpg.delete_item(t)


def to_gpu_rgba(rgba: np.ndarray) -> np.ndarray:
    return (rgba.astype(np.float32) / 255.0).reshape(-1)
