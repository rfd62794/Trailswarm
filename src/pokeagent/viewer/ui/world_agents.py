"""World view: live agents, trails, badges and the hover tooltip (Dear PyGui draw calls over the map chunks)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.atlas import inplace
from pokeagent.viewer import roster, ui_scale
from pokeagent.viewer.health import OK, ring_alpha, ring_colour
from pokeagent.world import anim, draw, pill
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
                fade = (a + 8) / max(n, 1)
                dpg.draw_polyline(pts[a:a + 9], color=(*col, int(30 + 225 * fade * fade)), thickness=max(3, ui_scale.px(3)), parent=dl)
        pos = anim.place(t, lay, now)
        if pos is None:
            continue
        x, y, phase = pos
        cx, cy = vp.to_screen(x + 8, y + 8)
        v._points[t.id] = (x + 8, y + 8)
        half = ui_scale.sprite_px(vp.zoom, 9, MIN_SPRITE_PX / 2)
        state = v.health_state(t.id)
        dpg.draw_circle((cx, cy), half + 3, color=(*ring_colour(state, col), ring_alpha(state, now)), thickness=3 if state != OK else 2, parent=dl)
        dpg.draw_image(v._agent_tex(t.facing, phase, col), (cx - half, cy - half), (cx + half, cy + half), parent=dl)
        _label(dl, t.id[-8:], cx, cy - half - 3, vp.zoom, v.selected_id == t.id)
        tag = inplace.badge(lay, t.map)
        if tag:
            dpg.draw_text((cx + half + 4, cy + ui_scale.px(8)), tag, color=(255, 235, 150, 255), size=ui_scale.px(13), parent=dl)
        if t.battle and t.battle.ended_at is None:
            for a, b in (((-7, -34), (7, -20)), ((7, -34), (-7, -20))):
                dpg.draw_line((cx + a[0], cy + a[1]), (cx + b[0], cy + b[1]), color=(230, 40, 40, 255), thickness=3, parent=dl)
            dpg.draw_text((cx - ui_scale.px(24), cy - ui_scale.px(52)), t.battle.species or "?", color=(255, 220, 80, 255), size=ui_scale.px(14), parent=dl)


def _label(dl, text: str, cx: float, top: float, zoom: float, selected: bool) -> None:
    """The agent's name on a dark rounded pill above its sprite (readable over busy tiles; scales with zoom)."""
    size = ui_scale.px(13)
    pl = pill.pill(cx, top, len(text) * size * 0.55, size, zoom)
    dpg.draw_rectangle((pl.x0, pl.y0), (pl.x1, pl.y1), rounding=pl.radius, fill=pill.PILL_FILL,
                       color=(255, 255, 160, 255) if selected else (0, 0, 0, 0), parent=dl)
    dpg.draw_text((pl.text_x, pl.text_y), text, color=pill.PILL_TEXT, size=max(10, int(pl.font)), parent=dl)


def draw_hover(v) -> None:
    m = v._mouse()
    if not m:
        return
    aid = pick(v._points, v.vp, *m)
    t = v.wm.track(aid) if aid else None      # None: the agent exited since _points was built
    if t is not None:
        row = next((r for r in v.roster_rows() if r.agent_id == aid), None)
        lines = [row.text() if row else aid, f"step {t.step}  goal: {t.goal or '-'}", "in battle" if t.battle and not t.battle.ended_at else ""]
    else:
        loc = locate(v.vl or v.world.layout, *v.vp.to_world(*m))
        lines = [f"{loc}"] if loc else []
        lines += v.interiors.tooltip(loc[0] if loc and loc[0] in (v.interiors.plan.anchors if v.interiors.plan else ()) else v.interiors.hover)
    lines = [s for s in lines if s]
    for i, s in enumerate(lines):
        dpg.draw_text((m[0] + ui_scale.px(14), m[1] + ui_scale.px(8 + 15 * i)), s, color=(255, 255, 160, 255), size=ui_scale.px(14), parent=v.canvas)
