"""World view: live agents, trails, badges and the hover tooltip (Dear PyGui draw calls over the map chunks)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace
from pokeagent.viewer import ui_scale
from pokeagent.world import anim, draw
from pokeagent.world.view import locate, pick

MIN_SPRITE_PX = 26      # an agent is never drawn smaller than this (1x px; scaled by DPI), however far out you zoom


def draw_agents(v, now: float) -> None:
    """Trails, agent sprites, labels, in-place badges and battle marks (screen space, over the chunks)."""
    w, vp, dl = v.world, v.vp, v.canvas
    lay = v.vl or w.layout
    tracks = v.wm.tracks()
    ids = [t.id for t in tracks]
    v._points = {}
    for t in tracks:
        col = draw.agent_colour(t.id, ids)
        if v.trails:
            pts = [vp.to_screen(*p) for p in anim.trail_points(t, lay, 120)]
            n = len(pts)
            for a in range(0, n - 1, 8):
                dpg.draw_polyline(pts[a:a + 9], color=(*col, 60 + 180 * a // max(n, 1)), thickness=max(2, ui_scale.px(2)), parent=dl)
        pos = anim.place(t, lay, now)
        if pos is None:
            continue
        x, y, phase = pos
        cx, cy = vp.to_screen(x + 8, y + 8)
        v._points[t.id] = (x + 8, y + 8)
        half = ui_scale.sprite_px(vp.zoom, 9, MIN_SPRITE_PX / 2)
        dpg.draw_circle((cx, cy), half + 3, color=(*col, 255), thickness=2, parent=dl)
        dpg.draw_image(v._agent_tex(t.facing, phase, col), (cx - half, cy - half), (cx + half, cy + half), parent=dl)
        dpg.draw_text((cx + half + 4, cy - ui_scale.px(8)), t.id[-8:], color=(255, 255, 255, 255), size=ui_scale.px(14), parent=dl)
        tag = inplace.badge(lay, t.map)
        if tag:
            dpg.draw_text((cx + half + 4, cy + ui_scale.px(8)), tag, color=(255, 235, 150, 255), size=ui_scale.px(13), parent=dl)
        if t.battle and t.battle.ended_at is None:
            for a, b in (((-7, -34), (7, -20)), ((7, -34), (-7, -20))):
                dpg.draw_line((cx + a[0], cy + a[1]), (cx + b[0], cy + b[1]), color=(230, 40, 40, 255), thickness=3, parent=dl)
            dpg.draw_text((cx - ui_scale.px(24), cy - ui_scale.px(52)), t.battle.species or "?", color=(255, 220, 80, 255), size=ui_scale.px(14), parent=dl)


def draw_hover(v) -> None:
    m = v._mouse()
    if not m:
        return
    aid = pick(v._points, v.vp, *m)
    if aid:
        t = v.wm.track(aid)
        lines = [aid, f"step {t.step}  goal: {t.goal or '-'}", "in battle" if t.battle and not t.battle.ended_at else ""]
    else:
        loc = locate(v.vl or v.world.layout, *v.vp.to_world(*m))
        lines = [f"{loc}"] if loc else []
        lines += v.interiors.tooltip(loc[0] if loc and loc[0] in (v.interiors.plan.anchors if v.interiors.plan else ()) else v.interiors.hover)
    lines = [s for s in lines if s]
    for i, s in enumerate(lines):
        dpg.draw_text((m[0] + ui_scale.px(14), m[1] + ui_scale.px(8 + 15 * i)), s, color=(255, 255, 160, 255), size=ui_scale.px(14), parent=v.canvas)
