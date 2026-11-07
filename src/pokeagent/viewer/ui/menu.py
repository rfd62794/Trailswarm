"""The viewport menu bar: View > Stadium pane (checkbox), Save layout, Reset layout.

No keyboard shortcuts anywhere here (key handling stays with keys.py/steering, untouched).
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

MENU_STADIUM = "menu_stadium_pane"


def build(win) -> None:
    """``win`` is the ViewerWindow: supplies stadium_visible/set_stadium_pref/save_layout/reset_layout."""
    with dpg.viewport_menu_bar():
        with dpg.menu(label="View"):
            dpg.add_menu_item(label="Stadium pane", check=True, tag=MENU_STADIUM,
                              default_value=win.stadium_visible(),
                              callback=lambda s, a, u: win.set_stadium_pref(a))
            dpg.add_menu_item(label="Save layout", callback=lambda s, a, u: win.save_layout())
            dpg.add_menu_item(label="Reset layout (applies on restart)",
                              callback=lambda s, a, u: win.reset_layout())
