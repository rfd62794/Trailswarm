"""World view, in-place interiors: plan + mode state, the per-frame view layout and the DPG drawing of the shown interiors.

Interior pixels come from the ROM (``atlas.inplace_render.InteriorImages``) as small cached textures drawn over the chunks:
a shadow and the tinted, framed interior; the outdoor map itself is never dimmed. Pure decisions live in ``atlas.inplace``; the
stretch swap and the layout editor are ``world_stretch`` / ``world_edit``. Nothing here may break the map: any failure in the
per-frame path is logged once and the view falls back to the plain layout with no interiors.
"""
from __future__ import annotations

import logging
import time

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace, inplace_render
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.world import CELL, WorldLayout
from pokeagent.viewer import ui_scale
from pokeagent.viewer.ui.world_edit import EditLayout
from pokeagent.viewer.ui.world_stretch import StretchSwap
from pokeagent.world.export import full_world
from pokeagent.world.pyramid import to_gpu

log = logging.getLogger(__name__)
MAX_RENDER = 8                 # new interior renders per frame: choosing an in-place mode fills in over a few frames
MAX_TEX = 400                  # interior textures are small (one per anchored interior and scale); trimmed past this


class InteriorLayer:
    def __init__(self, view) -> None:
        self.view = view
        self.ov = Overrides.load()           # defaults + runs/atlas/layout_overrides.json (+ the saved mode choice)
        self.mode = self.ov.mode or inplace.DEFAULT_MODE     # rooms in place (fit) unless the user chose otherwise
        self.selected: int | None = None
        self.hover: int | None = None
        self.plan: inplace.Plan | None = None
        self.shown: set[int] = set()
        self.vl: WorldLayout | None = None
        self.edit = EditLayout(self)
        self.swap = StretchSwap(self)
        self._rev, self._erev, self._wid = -1, -1, None
        self._walk: dict = {}
        self._tex: dict = {}
        self._images: inplace_render.InteriorImages | None = None
        self._used: set = set()
        self._failed: tuple | None = None    # input signature whose planning/drawing raised: skipped until it changes
        self._logged = ""

    @property
    def eff_mode(self) -> str:
        return "inplace" if self.mode == "stretch" else self.mode

    def set_mode(self, mode: str) -> None:
        """The Interiors selector: apply now and remember it (saved with the other overrides)."""
        self.mode = mode
        self.swap.force_full = False
        self.ov.set_mode(mode)
        self.edit.touch()

    def _sig(self) -> tuple:
        return (self.mode, self.edit.rev, self.view.wm.rev, id(self.view.world))

    def _fail(self, where: str, exc: Exception) -> None:
        msg = f"{where}: {type(exc).__name__}: {exc}"
        if msg != self._logged:                  # once per distinct failure, not once per frame
            self._logged = msg
            log.exception("in-place interiors disabled (%s)", msg)
        self._failed, self.shown, self.vl = self._sig(), set(), None
        self.swap.force_full = True              # a compact layout parks anchored rooms off-canvas: go back to the full world

    # -- per frame ------------------------------------------------------------------------
    def layout(self, zoom: float, inside: tuple[int, ...]) -> WorldLayout:
        """The layout agents/trails/hit tests use this frame (replans when learned warps or edits change)."""
        v = self.view
        w = v.world
        self.edit.tick(time.monotonic())
        if self._failed == self._sig():
            return full_world(w).layout          # same as the failure path: never the compact layout with off-canvas rooms
        try:
            self._purge(w)
            if self.plan is None or (self._rev, self._erev, self._wid) != (v.wm.rev, self.edit.rev, id(w)):
                self._rev, self._erev, self._wid = v.wm.rev, self.edit.rev, id(w)
                self.plan = inplace.plan_interiors(w.rom, w.headers, w.layout, v.wm.union_model(), self._walk, self.ov)
            mode = self.eff_mode
            if mode == "inset":  # the original atlas: agents stay inside their room in the grid, never pinned to doors
                self.shown, self.vl = set(), None
                return w.layout
            self.shown = inplace.shown_set(mode, self.plan.anchors, zoom, self.hover, self.selected, inside, self.plan.hidden)
            top = self.hover if self.hover in self.shown else self.selected
            self.vl = inplace.view_layout(w.layout, self.plan.anchors, self.plan.xf(mode), self.shown, top)
            return self.vl
        except Exception as exc:
            self._fail("layout", exc)
            return full_world(w).layout          # never a layout whose anchored rooms sit at the off-canvas sentinel

    def update_hover(self, mouse) -> None:
        """Hovered interior under the mouse (any anchored one: auto reveals it), None off the map."""
        v = self.view
        if mouse is None or self.plan is None or self.eff_mode == "inset" or self._failed == self._sig():
            self.hover = None
            return
        wx, wy = v.vp.to_world(*mouse)
        self.hover = inplace.hit(v.world.layout, self.plan.anchors, self.plan.xf(self.eff_mode), wx / CELL, wy / CELL, self.selected)

    def tooltip(self, m: int | None) -> list[str]:
        return inplace.legend(self.plan.anchors, self.plan.xf(self.eff_mode), m) if m is not None and self.plan else []

    # -- textures (never deleted while a frame may still draw them: trimmed at the start of the next frame) ----------
    def _purge(self, w) -> None:
        stale = [k for k in self._tex if k[0] != id(w)]
        if len(self._tex) > MAX_TEX:
            stale += [k for k in self._tex if k not in self._used and k not in stale]
        for k in stale:
            dpg.delete_item(self._tex.pop(k))
        self._used = set()

    def _texture(self, m: int, s: float, depth: int):
        w = self.view.world
        key = (id(w), m, s, depth)
        if key not in self._tex:
            if self._images is None:
                self._images = inplace_render.InteriorImages(w.rom, w.headers)
            src = self._images.get(m)
            if src is None:
                return None                      # over this frame's render budget: not drawn yet
            img = inplace_render.interior_tile(src, s, depth)
            self._tex[key] = dpg.add_static_texture(img.shape[1], img.shape[0], to_gpu(img), parent="world_tex")
        self._used.add(key)
        return self._tex[key]

    def draw(self, dl) -> None:
        v, w = self.view, self.view.world
        msg, until = self.swap.message
        if msg and time.monotonic() < until:
            dpg.draw_text((12, 12), msg, color=(255, 120, 90, 255), size=ui_scale.px(16), parent=dl)
        if not self.shown or self.plan is None or self.vl is None or self._failed == self._sig():
            return
        try:
            top = self.selected if self.selected in self.shown else self.hover
            if self._images is None:
                self._images = inplace_render.InteriorImages(w.rom, w.headers)
            self._images.begin_frame(MAX_RENDER)
            for m in inplace.z_order(self.plan.anchors, self.shown, top):
                t, pl = self.vl.xf[m], w.layout.places[m]
                p0 = v.vp.to_screen(t.ox * CELL, t.oy * CELL)
                p1 = v.vp.to_screen((t.ox + pl.w * t.s) * CELL, (t.oy + pl.h * t.s) * CELL)
                off = 6 * v.vp.zoom
                dpg.draw_rectangle((p0[0] + off, p0[1] + off), (p1[0] + off, p1[1] + off), fill=(0, 0, 0, 120), color=(0, 0, 0, 0), parent=dl)
                tex = self._texture(m, t.s, self.plan.anchors[m].depth)
                if tex is not None:
                    dpg.draw_image(tex, p0, p1, parent=dl)
        except Exception as exc:
            self._fail("draw", exc)

    # -- hooks the view calls (kept thin: the work is in world_stretch / world_edit) -------------
    def tick_world(self) -> None:
        self.swap.tick()

    def press(self) -> None:
        self.edit.press()

    def release(self) -> None:
        self.edit.release()

    def edit_drag(self, dsx: float, dsy: float) -> bool:
        return self.edit.drag(dsx, dsy)

    def edit_wheel(self, delta: float) -> bool:
        return self.edit.wheel(delta)

    def reset(self, everything: bool = False) -> None:
        self.edit.reset(everything)
