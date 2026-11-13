"""Dear PyGui theme: the dark viewer palette (spec colours live in viewer.panels)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.health import ANOMALY, OK, SLOW, STALLED
from pokeagent.viewer.theme_colours import palette, toggle

# card header tint per health state (ok = the header's current plain tint); also the badge colour
HEADER_COLOUR = {
    OK: (255, 255, 255, 255),
    SLOW: (255, 200, 80, 255),      # amber
    STALLED: (255, 80, 80, 255),    # red
    ANOMALY: (255, 80, 255, 255),   # magenta
}
_STATE_THEMES: dict[str, int] = {}
_mode = "dark"
_bound: list[int] = []


def health_theme(state: str) -> int | None:
    """One dpg theme per health state (created once, memoised); None for ok (no override)."""
    if state == OK:
        return None
    if state not in _STATE_THEMES:
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, HEADER_COLOUR.get(state, HEADER_COLOUR[OK]))
        _STATE_THEMES[state] = t
    return _STATE_THEMES[state]


def _rgba(hex_color: str, a: int = 255) -> tuple[int, int, int, int]:
    c = hex_color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a


def mode() -> str:
    return _mode


def apply(mode: str | None = None) -> None:
    """Register and bind the viewer theme (call after create_context, before setup). ``mode``: dark | light (the chrome only;
    the card panels keep their dark images)."""
    global _mode
    _mode = mode or _mode
    c = palette(_mode)
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, _rgba(c["bg"]))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, _rgba(c["pane"]))
            dpg.add_theme_color(dpg.mvThemeCol_Text, _rgba(c["text"]))
            dpg.add_theme_color(dpg.mvThemeCol_Button, _rgba(c["button"]))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _rgba(c["button_hover"]))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, _rgba(c["button_active"]))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, _rgba(c["frame"]))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, _rgba(c["frame_hover"]))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, _rgba(c["bg"], 200))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, _rgba(c["dim"], 160))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 6, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 3)
    dpg.bind_theme(theme)
    while _bound:
        dpg.delete_item(_bound.pop())
    _bound.append(theme)


def toggle_mode() -> str:
    """Flip dark <-> light and rebind."""
    apply(toggle(_mode))
    return _mode
