"""World view, in-place interiors: plan + mode state, the per-frame view layout and the DPG drawing of the shown interiors.

Interior pixels come from the inset grid (``atlas.inplace_render.interior_tile``) as small cached textures drawn over the
chunks: a dim over the outdoor map, a shadow, the tinted framed interior. Pure decisions live in ``atlas.inplace``.
"""
from __future__ import annotations

import threading

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace, inplace_render
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.world import CELL, WorldLayout
from pokeagent.world.export import stretch_world
from pokeagent.world.pyramid import Pyramid, to_gpu

MAX_TILES = 48


class InteriorLayer:
    def __init__(self, view) -> None:
        self.view = view
        self.mode = "auto"
        self.selected: int | None = None
        self.hover: int | None = None
        self.plan: inplace.Plan | None = None
        self.ov = Overrides.load()           # defaults + runs/atlas/layout_overrides.json (edited live, saved at once)
        self.editing = False
        self.drag_map: int | None = None
        self.shown: set[int] = set()
        self._pairs: dict = {}                # 'plain' / 'stretch' -> (World, Pyramid)
        self._building = False
        self._wid = None
        self._rev = -1
        self._walk: dict = {}
        self._tex: dict = {}

    def layout(self, zoom: float, inside: tuple[int, ...]) -> WorldLayout:
        """The layout agents/trails/hit tests use this frame (recomputes the plan when learned warps change)."""
        v = self.view
        w = v.world
        if self.plan is None or self._rev != v.wm.rev or self._wid != id(w):
            self._rev, self._wid = v.wm.rev, id(w)
            self.plan = inplace.plan_interiors(w.rom, w.headers, w.layout, v.wm.union_model(), self._walk, self.ov)
        mode = self.eff_mode
        self.shown = inplace.shown_set(mode, self.plan.anchors, zoom, self.hover, self.selected, inside, self.plan.hidden)
        top = self.hover if self.hover in self.shown else self.selected
        self.vl = inplace.view_layout(w.layout, self.plan.anchors, self.plan.xf(mode), self.shown, top)
        return self.vl

    def update_hover(self, mouse) -> None:
        """Hovered interior under the mouse (any anchored one: auto reveals it), None off the map."""
        v = self.view
        if mouse is None or self.plan is None or self.eff_mode == "inset":
            self.hover = None
            return
        wx, wy = v.vp.to_world(*mouse)
        self.hover = inplace.hit(v.world.layout, self.plan.anchors, self.plan.xf(self.eff_mode), wx / CELL, wy / CELL, self.selected)

    def _texture(self, m: int, s: float, depth: int):
        key = (m, s, depth, id(self.view.world))
        if key not in self._tex:
            if len(self._tex) >= MAX_TILES:
                dpg.delete_item(self._tex.pop(next(iter(self._tex))))
            img = inplace_render.interior_tile(self.view.world.base, self.view.world.layout, m, s, depth)
            self._tex[key] = dpg.add_static_texture(img.shape[1], img.shape[0], to_gpu(img), parent="world_tex")
        return self._tex[key]

    def draw(self, dl) -> None:
        if not self.shown or self.plan is None:
            return
        v, w = self.view, self.view.world
        a, b = v.vp.to_screen(0, 0), v.vp.to_screen(w.layout.width * CELL, w.layout.outdoor_height * CELL)
        dpg.draw_rectangle(a, b, fill=(0, 0, 0, int(255 * (1 - inplace_render.DIM))), color=(0, 0, 0, 0), parent=dl)
        for m in inplace.z_order(self.plan.anchors, self.shown, self.selected if self.selected in self.shown else self.hover):
            t, pl = self.vl.xf[m], w.layout.places[m]
            p0 = v.vp.to_screen(t.ox * CELL, t.oy * CELL)
            p1 = v.vp.to_screen((t.ox + pl.w * t.s) * CELL, (t.oy + pl.h * t.s) * CELL)
            off = 6 * v.vp.zoom
            dpg.draw_rectangle((p0[0] + off, p0[1] + off), (p1[0] + off, p1[1] + off), fill=(0, 0, 0, 120), color=(0, 0, 0, 0), parent=dl)
            dpg.draw_image(self._texture(m, t.s, self.plan.anchors[m].depth), p0, p1, parent=dl)

    def tooltip(self, m: int | None) -> list[str]:
        return inplace.legend(self.plan.anchors, self.plan.xf(self.eff_mode), m) if m is not None and self.plan else []

    @property
    def eff_mode(self) -> str:
        return "inplace" if self.mode == "stretch" else self.mode

    # -- stretch world (built once on a worker thread, then swapped in by the view) ------------
    def tick_world(self) -> None:
        v = self.view
        if v.world is None:
            return
        want = "stretch" if self.mode == "stretch" else "plain"
        have = "stretch" if v.world.layout.warp is not None else "plain"
        self._pairs.setdefault(have, (v.world, v.pyr))
        if want == have or self._building:
            return
        if want in self._pairs:
            v._loaded = self._pairs[want]
            return
        self._building = True

        def work() -> None:
            try:
                w = stretch_world(self._pairs["plain"][0], v.wm.union_model(), self.ov)
                pyr = Pyramid(w.base)
                for f in (2, 4, 8):
                    pyr.level(f)
                self._pairs["stretch"] = (w, pyr)
            finally:
                self._building = False
        threading.Thread(target=work, daemon=True, name="world-stretch").start()

    # -- edit layout: drag = move, Ctrl+wheel = scale, reset; every change is saved at once -----
    def _changed(self) -> None:
        self._rev = -1                          # replan with the new overrides next frame
        try:
            self.ov.save()
        except OSError:
            pass

    def press(self) -> None:
        self.drag_map = self.hover if self.editing and self.hover in self.shown else None

    def edit_drag(self, dsx: float, dsy: float) -> bool:
        if self.drag_map is None:
            return False
        z = self.view.vp.zoom * CELL
        self.ov.move(self.drag_map, dsx / z, dsy / z)
        self._rev = -1
        return True

    def release(self) -> None:
        if self.drag_map is not None:
            self.drag_map = None
            self._changed()

    def edit_wheel(self, delta: float) -> bool:
        m = self.hover if self.hover in self.shown else self.selected
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        if not (self.editing and ctrl and m is not None and self.plan and m in self.plan.xf(self.eff_mode)):
            return False
        self.ov.rescale(m, self.plan.xf(self.eff_mode)[m].s, 1.1 if float(delta) > 0 else 1 / 1.1)
        self._changed()
        return True

    def reset(self, everything: bool = False) -> None:
        m = self.selected if self.selected is not None else self.hover
        if everything or m is not None:
            self.ov.reset(None if everything else m)
            self._changed()
