"""What the World canvas shows before there is a map: a filled backdrop and a clear state line (never a blank canvas)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer import ui_scale
from pokeagent.world.palette import GB_GREENS


def lines(status: str, loaded: bool, n_agents: int) -> list[str]:
    """The message for the current state: loading / failed (status text) / loaded but nobody is on the map yet."""
    if not loaded:
        return [status or "loading Kanto from the ROM...", "the map appears here once it is rendered"]
    if n_agents == 0:
        return ["waiting for agents...", "start one with: pokeagent run, or open this view with --fake N"]
    return []


def draw_backdrop(dl, w: int, h: int) -> None:
    dpg.draw_rectangle((0, 0), (w, h), color=(0, 0, 0, 0), fill=(*GB_GREENS[0], 255), parent=dl)


def draw(dl, w: int, h: int, msg: list[str], over_map: bool = False) -> None:
    """Centred message lines; over a loaded map only a small pill (the map stays visible), otherwise the whole backdrop."""
    if not msg:
        return
    if not over_map:
        draw_backdrop(dl, w, h)
    size = ui_scale.px(18)
    y = h / 2 - size * len(msg) if not over_map else ui_scale.px(40)
    for i, s in enumerate(msg):
        tw = len(s) * size * 0.55
        x = max(8, w / 2 - tw / 2)
        if over_map:
            dpg.draw_rectangle((x - 8, y - 4), (x + tw + 8, y + size + 4), rounding=8, fill=(14, 24, 14, 215), color=(0, 0, 0, 0), parent=dl)
        dpg.draw_text((x, y), s, color=(155, 188, 15, 255) if i == 0 else (139, 172, 15, 255), size=size - (4 if i else 0), parent=dl)
        y += size * 1.5
