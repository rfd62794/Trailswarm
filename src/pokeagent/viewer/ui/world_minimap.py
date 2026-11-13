"""World view minimap: the coarsest map level as one texture, the visible viewport outlined, agent dots, click to jump."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer import ui_scale
from pokeagent.world.draw import agent_colour
from pokeagent.world.minimap import MiniMap
from pokeagent.world.pyramid import LEVELS, to_gpu

MARGIN = 10


class Minimap:
    def __init__(self, view) -> None:
        self.view = view
        self.on = True
        self.dragging = False
        self._tex = None
        self._for = None

    def _geom(self) -> tuple[MiniMap, float, float] | None:
        """The map maths plus the box's top-left corner in canvas pixels (bottom-right of the canvas)."""
        v = self.view
        if v.pyr is None or not self.on:
            return None
        mm = MiniMap(v.vp.world_w, v.vp.world_h, ui_scale.px(220), ui_scale.px(160))
        w, h = mm.size
        return mm, v.vp.screen_w - w - ui_scale.px(MARGIN), v.vp.screen_h - h - ui_scale.px(MARGIN)

    def _texture(self):
        v = self.view
        if self._for is not id(v.pyr):
            if self._tex is not None:
                dpg.delete_item(self._tex)
            rgb = v.pyr.level(LEVELS[-1])
            self._tex = dpg.add_static_texture(rgb.shape[1], rgb.shape[0], to_gpu(rgb), parent="world_tex")
            self._for = id(v.pyr)
        return self._tex

    def hit(self, m) -> bool:
        g = self._geom()
        return bool(g and m and g[0].contains(m[0] - g[1], m[1] - g[2]))

    def jump(self, m) -> None:
        """Centre the view on the clicked world point (and stop following: the user chose a place)."""
        g = self._geom()
        if g and m:
            self.view.follow.stop()
            self.view.vp.center_on(*g[0].to_world(m[0] - g[1], m[1] - g[2]))

    def draw(self, dl) -> None:
        g = self._geom()
        if g is None:
            return
        mm, ox, oy = g
        w, h = mm.size
        dpg.draw_rectangle((ox - 2, oy - 2), (ox + w + 2, oy + h + 2), color=(155, 188, 15, 255), fill=(15, 56, 15, 255), parent=dl)
        dpg.draw_image(self._texture(), (ox, oy), (ox + w, oy + h), parent=dl)
        for aid, p in self.view._points.items():
            dx, dy = mm.agent_dot(*p)
            dpg.draw_circle((ox + dx, oy + dy), 3, color=(0, 0, 0, 255), fill=(*agent_colour(aid), 255), parent=dl)
        x0, y0, x1, y1 = mm.viewport_rect(self.view.vp.visible())
        dpg.draw_rectangle((ox + x0, oy + y0), (ox + max(x1, x0 + 2), oy + max(y1, y0 + 2)), color=(255, 255, 255, 255), thickness=2, parent=dl)
