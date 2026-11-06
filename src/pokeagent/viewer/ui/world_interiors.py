"""World view, in-place interiors: plan + mode state, the per-frame view layout and the DPG drawing of the shown interiors.

Interior pixels come from the inset grid (``atlas.inplace_render.interior_tile``) as small cached textures drawn over the
chunks: a dim over the outdoor map, a shadow, the tinted framed interior. Pure decisions live in ``atlas.inplace``.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace, inplace_render
from pokeagent.atlas.world import CELL, WorldLayout
from pokeagent.world.pyramid import to_gpu

MAX_TILES = 48


class InteriorLayer:
    def __init__(self, view) -> None:
        self.view = view
        self.mode = "auto"
        self.selected: int | None = None
        self.hover: int | None = None
        self.plan: inplace.Plan | None = None
        self._rev = -1
        self._walk: dict = {}
        self._tex: dict = {}

    def layout(self, zoom: float, inside: tuple[int, ...]) -> WorldLayout:
        """The layout agents/trails/hit tests use this frame (recomputes the plan when learned warps change)."""
        v = self.view
        w = v.world
        if self.plan is None or self._rev != v.wm.rev:
            self._rev = v.wm.rev
            self.plan = inplace.plan_interiors(w.rom, w.headers, w.layout, v.wm.union_model(), self._walk)
        self.shown = inplace.shown_set(self.mode, self.plan.anchors, zoom, self.hover, self.selected, inside)
        top = self.hover if self.hover in self.shown else self.selected
        self.vl = inplace.view_layout(w.layout, self.plan.anchors, self.plan.xf(self.mode), self.shown, top)
        return self.vl

    def update_hover(self, mouse) -> None:
        """Hovered interior under the mouse (any anchored one: auto reveals it), None off the map."""
        v = self.view
        if mouse is None or self.plan is None or self.mode == "inset":
            self.hover = None
            return
        wx, wy = v.vp.to_world(*mouse)
        self.hover = inplace.hit(v.world.layout, self.plan.anchors, self.plan.xf(self.mode), wx / CELL, wy / CELL, self.selected)

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
        return inplace.legend(self.plan.anchors, self.plan.xf(self.mode), m) if m is not None and self.plan else []
