"""World mode: the stitched Kanto as chunked textures with zoom/pan, every agent drawn live over it.

All Dear PyGui calls for the map live here (side panel: ``world_side``). Heavy work (ROM render, layer composition) runs on a
worker thread; the render loop only draws what is ready. Hit testing and zoom maths are pure (``pokeagent.world.view``).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

import dearpygui.dearpygui as dpg
import numpy as np

from pokeagent.atlas import sprites
from pokeagent.viewer import ui_scale
from pokeagent.viewer import roster
from pokeagent.viewer.ui import tags, world_layers, world_status
from pokeagent.viewer.ui.world_minimap import Minimap
from pokeagent.viewer.ui.world_agents import draw_agents, draw_hover
from pokeagent.viewer.ui.world_interiors import InteriorLayer
from pokeagent.world.follow import Follow
from pokeagent.world.pyramid import LEVELS, Pyramid, to_gpu
from pokeagent.world.view import Viewport, locate, pick

log = logging.getLogger(__name__)
TEX = "world_tex"
MAX_UPLOADS = 2         # chunk uploads per frame (a pan never stalls the UI on a burst of 16 MB uploads)
MAX_TEX = 40            # chunk textures kept on the GPU (about 16 MB each)


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
        self.interiors = InteriorLayer(self)
        self._frame_err = ""
        self.vl = None                          # this frame's view layout (in-place interiors)
        self.status = "loading Kanto from the ROM..."
        self._tex: OrderedDict = OrderedDict()
        self._tex_pyr: Pyramid | None = None   # the pyramid ``_tex`` chunks were cut from (held: identity stays unique)
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
        self.follow = Follow()
        self.health_store = None                # HealthStore (bound by the side panel); ring colour per agent
        self.selected_id: str | None = None     # last agent clicked on the map
        self.follow_selected = False            # side panel toggle: keep the camera on the selected agent
        self.tint = True                        # Game Boy green palette (reloads the map when toggled)
        self.mini = Minimap(self)
        self._follow_t: float | None = None
        if not dpg.does_item_exist(TEX):
            dpg.add_texture_registry(tag=TEX, show=False)
        self.area = dpg.add_child_window(parent=parent, width=10, height=10, border=False, no_scrollbar=True, tag=tags.WORLD_AREA,
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
        return world_layers.want(self)

    def _maybe_rebuild(self, now: float) -> None:
        world_layers.maybe_rebuild(self, now)

    # -- textures ------------------------------------------------------------------------
    def _drop_chunks(self) -> None:
        """Delete every chunk texture (each is ~16 MB of floats, plus DPG's CPU copy)."""
        while self._tex:
            dpg.delete_item(self._tex.popitem(last=False)[1])

    def _drop_sprites(self) -> None:
        for tag in self._sprite_tex.values():
            dpg.delete_item(tag)
        self._sprite_tex.clear()

    def _adopt_pyramid(self, pyr: Pyramid | None) -> None:
        """Make ``pyr`` the drawn pyramid. Chunk textures of any other pyramid are dead weight (a layer rebuild or a world swap
        replaces the pixels) and would otherwise sit on the GPU until the LRU got round to them - up to MAX_TEX x 16 MB."""
        if pyr is not self._tex_pyr:
            self._drop_chunks()
            self._tex_pyr = pyr
        self.pyr = pyr

    def _chunk_tex(self, f: int, cx: int, cy: int, force: bool = False):
        """The texture of a chunk if it is on the GPU; otherwise upload it - at most MAX_UPLOADS per frame (None = not yet)."""
        if self.pyr is not self._tex_pyr:
            self._adopt_pyramid(self.pyr)
        key = (f, cx, cy)
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
        return self._sprite_tex[key]       # bounded: facings x phases x the 10-colour agent palette, never per agent id

    def prune_agents(self, live) -> None:
        """Forget view state about agents that left (selection, follow target, hit-test points)."""
        live = set(live)
        if self.selected_id is not None and self.selected_id not in live:
            self.selected_id = None
        if self.follow.agent_id is not None and self.follow.agent_id not in live:
            self.follow.stop()
        for aid in [a for a in self._points if a not in live]:
            del self._points[aid]

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
        if m and self.pyr and not self.interiors.edit_wheel(delta):
            self.vp.step_zoom_at(m[0], m[1], 1 if float(delta) > 0 else -1)

    def _click(self) -> None:
        self._down_at = self._mouse()
        self.mini.dragging = self.mini.hit(self._down_at)
        if self.mini.dragging:
            self.mini.jump(self._down_at)
            self._down_at = None
            return
        self.interiors.press()

    def _release(self) -> None:
        m, d = self._mouse(), self._down_at
        self.mini.dragging = False
        self.interiors.release()
        self._down_at = self._last_mouse = None
        if m and d and abs(m[0] - d[0]) < 4 and abs(m[1] - d[1]) < 4 and self.world:
            aid = pick(self._points, self.vp, *m)
            if aid:
                self._on_select(aid)
                self.selected_id = aid
                self.follow.start(aid, time.monotonic())
            elif self.side:
                self.follow.stop()
                loc = locate(self.vl or self.world.layout, *self.vp.to_world(*m))
                self.interiors.selected = loc[0] if loc and self.interiors.plan and loc[0] in self.interiors.plan.anchors else None
                if loc:
                    self.side.show_tile(*loc)

    def health_state(self, agent_id: str) -> str:
        return self.health_store.health(agent_id).state if self.health_store is not None else "ok"

    def roster_rows(self) -> list:
        model = self.side.host[0] if self.side is not None and self.side.host else None
        return roster.rows(self.wm.tracks(), model.snapshot if model else (lambda _a: None), self.health_state, time.monotonic())

    def set_tint(self, on: bool) -> None:
        """Game Boy greens on/off: reload the map (the viewport and interior state carry over like any world swap)."""
        from pokeagent.world.export import load_for_view
        self.tint = on
        threading.Thread(target=self._load, args=(lambda: load_for_view(tint=on),), daemon=True, name="world-load").start()

    def follow_agent(self, agent_id: str) -> None:
        """Start following (from a card or a mode switch): centre at once when its position is known."""
        self.follow.start(agent_id, time.monotonic())
        p = self._points.get(agent_id)
        if p is not None:
            self.vp.center_on(*p)

    def _double(self) -> None:
        m = self._mouse()
        aid = pick(self._points, self.vp, *m) if m else None
        if aid:
            self._on_focus(aid)

    def _drag(self) -> None:
        m = self._mouse()
        if m and self.mini.dragging and dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            self.mini.jump(m)                                  # dragging inside the minimap scrubs the view
        elif m and dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            if self._last_mouse:
                d = (m[0] - self._last_mouse[0], m[1] - self._last_mouse[1])
                if not self.interiors.edit_drag(*d):
                    self.vp.pan(*d)
                    if d[0] or d[1]:
                        self.follow.stop()
            self._last_mouse = m
        else:
            self._last_mouse = None

    # -- per frame -----------------------------------------------------------------------
    def fit(self, w: int, h: int) -> None:
        """Size the area to the viewport (the canvas takes what the side panel leaves)."""
        side_w = ui_scale.side_panel_width(w) if self.side else 0
        dpg.configure_item(self.area, width=w - 8, height=h)
        cw, ch = max(100, w - side_w - 24), max(100, h - 8)
        dpg.configure_item(self.canvas, width=cw, height=ch)
        self.vp.resize(cw, ch)
        if self.side:
            self.side.fit(side_w, h)

    def update(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        dl = self.canvas
        if not self._started:       # the ROM render starts the first time world mode is shown
            self._started = True
            threading.Thread(target=self._load, args=(self._loader,), daemon=True, name="world-load").start()
        dpg.delete_item(dl, children_only=True)
        if self._loaded is not None:
            prev_world, prev_vp = self.world, self.vp
            (self.world, pyr), self._loaded = self._loaded, None
            self._adopt_pyramid(pyr)
            self._drop_sprites()                    # drawn from the old world's sprite book (and its tint)
            self.vp = Viewport(*self.world.layout.size_px, self.vp.screen_w, self.vp.screen_h)
            if not (prev_world is not None and self.interiors.swap.restore(prev_world, prev_vp, self.vp)):
                self.vp.fit()
            self._built_for, self._pending = None, None
            self.status = ""
        if self.pyr is None:
            world_status.draw(dl, self.vp.screen_w, self.vp.screen_h, world_status.lines(self.status, False, len(self.wm.tracks())))
            if self.side:
                self.side.update()
            return
        if self._pending is not None:
            self._adopt_pyramid(self._pending)
            self._pending = None
        try:
            self._frame(now, dl)
        except Exception as exc:                  # nothing in the World view may kill the window: log once, skip the frame
            if str(exc) != self._frame_err:
                self._frame_err = str(exc)
                log.exception("world view frame skipped")

    def _frame(self, now: float, dl) -> None:
        self.interiors.tick_world()
        self.prune_agents(self.wm.ids())
        self._maybe_rebuild(now)
        self._drag()
        t = self.follow.target(self._points, now)
        if t is not None:
            self.follow.step(self.vp, t, 0.0 if self._follow_t is None else now - self._follow_t)
        self._follow_t = now
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
        tracks = tuple(t.map for t in self.wm.tracks() if t.placed)
        self.interiors.update_hover(self._mouse())
        self.vl = self.interiors.layout(vp.zoom, tracks)
        self.interiors.draw(dl)
        draw_agents(self, now)
        self.mini.draw(dl)
        draw_hover(self)
        world_status.draw(dl, vp.screen_w, vp.screen_h, world_status.lines("", True, len(self.wm.tracks())), over_map=True)
        if self.follow_selected and self.selected_id and not self.follow.active and not self._last_mouse:
            self.follow.start(self.selected_id, now)
        if self.follow.active:
            dpg.draw_text((12, 8), f"Following {self.follow.agent_id[-8:]} - drag the map or click empty space to stop",
                          size=ui_scale.px(15), parent=dl)
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

    def delete(self) -> None:
        self._drop_chunks()
        self._drop_sprites()
        self.mini.delete()
        self.interiors.delete()
        for t in (self.area, "world_input"):
            if dpg.does_item_exist(t):
                dpg.delete_item(t)


def to_gpu_rgba(rgba: np.ndarray) -> np.ndarray:
    return (rgba.astype(np.float32) / 255.0).reshape(-1)
