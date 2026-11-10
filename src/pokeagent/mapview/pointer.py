"""Mouse handling for the map canvas, moved out of view.py with no behaviour change.

Zoom on wheel, drag to pan (a pan wins over follow), press/release. The release also runs the
unified mode's click-to-pick: within the click slop the nearest drawn head becomes the pick and
re-enables "Follow selected".
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.mapview import pick
from pokeagent.mapview.controls import CANVAS


def mouse(win) -> tuple[float, float] | None:
    if not dpg.does_item_exist(CANVAS) or not dpg.is_item_hovered(CANVAS):
        return None
    mx, my = dpg.get_mouse_pos(local=False)
    ox, oy = dpg.get_item_rect_min(CANVAS)
    return mx - ox, my - oy


def wheel(win, delta) -> None:
    if (m := mouse(win)) is not None:
        win.vp.step_zoom_at(m[0], m[1], 1 if float(delta) > 0 else -1)


def press(win) -> None:
    win._down_at = mouse(win)


def release(win) -> None:
    m, d = mouse(win), win._down_at
    win._down_at = win._last_mouse = None
    if win.on_pick is not None and pick.is_click(d, m):
        if (hit := pick.pick_agent(m[0], m[1], win._drawn)) is not None:
            win.on_pick(*hit)
            win._set_follow_best(True)      # a pick re-enables Follow selected


def drag(win) -> None:
    m = mouse(win)
    down = m is not None and win._down_at is not None and dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
    if down and win._last_mouse is not None:
        d = (m[0] - win._last_mouse[0], m[1] - win._last_mouse[1])
        if d[0] or d[1]:
            win.vp.pan(*d)
            user_panned(win)
    win._last_mouse = m if down else None


def user_panned(win) -> None:
    """A manual pan wins: follow goes off (and the checkbox with it), the camera stays put."""
    win.follow.stop()
    if win.follow_best:
        win._set_follow_best(False)
