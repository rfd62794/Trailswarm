"""The window's Dear PyGui pieces: control row, canvas group, agent pane, input wiring.

Extracted from view.py with no behaviour change: every callback still lands on the
MapWindow it is handed, and the chunk-texture helpers are the same code moved, so the
existing window tests drive the same methods and see the same uploads.
"""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from pokeagent.mapview import overlay
from pokeagent.mapview.best import best_index
from pokeagent.world.pyramid import to_gpu

ROOT, TEX, CANVAS = "mapview_root", "mapview_tex", "mapview_canvas"
AGENTS_PANE, FOLLOW_CB = "mapview_agents", "mapview_follow_best"
FOLLOW_SEL = "mapview_follow_sel"           # the unified mode's "Follow selected" checkbox
MAX_UPLOADS, COARSEST_F = 2, 8          # uploads per frame, fallback pyramid depth
SPEEDS = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}


def build_body(win, parent=None) -> None:
    """Window, control row, canvas + agent panes; identical to the old inline build."""
    if parent is None:
        parent = dpg.add_window(tag=ROOT, label="Map view", no_scrollbar=True)
    cb = lambda f: (lambda s, a, u=None: f(a))
    with dpg.child_window(parent=parent, border=False, no_scrollbar=True):
        with dpg.group(horizontal=True):
            dpg.add_button(label="Pause", callback=cb(lambda a: win._toggle_pause()))
            dpg.add_combo(tuple(SPEEDS), default_value="1x", width=70,
                          callback=cb(lambda a: setattr(win.clock, "speed", SPEEDS.get(a, 1.0))))
            dpg.add_button(label="Fit", callback=cb(lambda a: win.vp.fit()))
            dpg.add_button(label="1:1", callback=cb(lambda a: win.vp.one_to_one()))
            for label, attr in (("trails", "trails"), ("marks", "marks")):
                dpg.add_checkbox(label=label, default_value=True,
                                 callback=cb(lambda a, attr=attr: setattr(win, attr, bool(a))))
            dpg.add_checkbox(label="Follow selected" if win.unified else "follow",
                             default_value=win.follow_best,
                             tag=FOLLOW_SEL if win.unified else FOLLOW_CB,
                             callback=cb(lambda a: win._set_follow_best(bool(a))))
        with dpg.group(horizontal=True):
            dpg.add_drawlist(width=800, height=560, tag=CANVAS)
            if not win.unified:  # unified: the agent list is the viewer side panel's instead
                dpg.add_child_window(width=230, border=True, tag=AGENTS_PANE)


def wire_input(win) -> None:
    cb = lambda f: (lambda s, a, u=None: f(a))
    with dpg.handler_registry(tag="mapview_input"):
        dpg.add_mouse_wheel_handler(callback=cb(win._wheel))
        dpg.add_mouse_click_handler(dpg.mvMouseButton_Left, callback=lambda s, a, u=None: win._press())
        dpg.add_mouse_release_handler(dpg.mvMouseButton_Left, callback=lambda s, a, u=None: win._release())


def follow_agent(win, agent: str) -> None:
    """Agent-table row click: follow that agent's best ghost's replay."""
    gs = [g for g in win.tables.ghosts if g.agent == agent]
    b = best_index(gs, win.tables.area_names)
    if b is not None:
        win._set_follow_best(False)
        win.follow.start(gs[b].run, time.monotonic())
        if (p := win._points().get(gs[b].run)) is not None:
            win.vp.center_on(*p)


def fill_agent_table(win) -> None:
    if not dpg.does_item_exist(AGENTS_PANE):
        return
    dpg.delete_item(AGENTS_PANE, children_only=True)
    for agent, cidx, n, far in win.agent_rows:
        with dpg.group(horizontal=True, parent=AGENTS_PANE):
            sw = dpg.add_drawlist(width=12, height=12)
            dpg.draw_rectangle((0, 0), (12, 12), parent=sw,
                               fill=(*[int(c) for c in overlay.PALETTE[cidx]], 255))
            dpg.add_selectable(label=f"{agent}  x{n}  {far}",
                               callback=lambda s, a, u, agent=agent: win._follow_agent(agent))


def chunk_tex(win, f: int, cx: int, cy: int):
    if (tag := win._tex.get(f, cx, cy)) is not None:
        return tag
    if win._tex_uploads >= MAX_UPLOADS:
        return _stale_tex(win, f, cx, cy)
    win._tex_uploads += 1
    rgb = win.pyr.chunk(f, cx, cy)
    tag = dpg.add_static_texture(rgb.shape[1], rgb.shape[0], to_gpu(rgb), parent=TEX)
    win._tex.put(f, cx, cy, tag)
    return tag


def _stale_tex(win, f: int, cx: int, cy: int):
    """Keep the old picture on screen until this chunk's replacement has uploaded."""
    tag = win._tex.fallback(f, cx, cy)
    win._used_stale = win._used_stale or tag is not None
    return tag


def draw_coarser(win, f: int, cx: int, cy: int) -> None:
    g = f * 2
    while g <= COARSEST_F:
        pcx, pcy, u0, v0, u1, v1 = win.pyr.parent(f, cx, cy, g)
        if (tex := chunk_tex(win, g, pcx, pcy)) is not None:
            x0, y0, x1, y1 = win.pyr.chunk_rect(f, cx, cy)
            dpg.draw_image(tex, win.vp.to_screen(x0, y0), win.vp.to_screen(x1, y1),
                           uv_min=(u0, v0), uv_max=(u1, v1), parent=CANVAS)
            return
        g *= 2
