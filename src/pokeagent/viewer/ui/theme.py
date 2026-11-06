"""Dear PyGui theme: the dark viewer palette (spec colours live in viewer.panels)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.panels import BG, PANE, TEXT, DIM


def _rgba(hex_color: str, a: int = 255) -> tuple[int, int, int, int]:
    c = hex_color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a


def apply() -> None:
    """Register and bind the viewer theme (call after create_context, before setup)."""
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, _rgba(BG))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, _rgba(PANE))
            dpg.add_theme_color(dpg.mvThemeCol_Text, _rgba(TEXT))
            dpg.add_theme_color(dpg.mvThemeCol_Button, _rgba("#2a2d34"))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _rgba("#3a3f4a"))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, _rgba("#4a5160"))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, _rgba("#141518"))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, _rgba("#23262d"))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, _rgba(BG, 200))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, _rgba(DIM, 160))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 6, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 3)
    dpg.bind_theme(theme)
