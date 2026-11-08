"""Every stable Dear PyGui tag in one place (layout persistence keys window state off them).

``init_file`` persists TOP-LEVEL windows only; child windows are not saved. A new top-level
window must be added to ``TOP_LEVEL_WINDOWS`` - a test asserts the set built at populate time.
"""
from __future__ import annotations

MAIN_WINDOW = "viewer_main"      # the one fixed viewport-filling window (unchanged string)
STADIUM_PANE = "stadium_pane"    # the toggleable top-level Stadium window (persisted by init_file)

# children of MAIN_WINDOW (kept as named constants; init_file does not persist these)
GRID_AREA = "grid_area"
FOCUS_AREA = "focus_area"
WORLD_AREA = "world_area"
WORLD_SIDE = "world_side"
HEALTH_PANEL = "health_panel"    # the expandable health section inside WORLD_SIDE
VIEWER_TEX = "viewer_tex"

# every window dpg.add_window creates at populate time (the documented list the test enforces)
TOP_LEVEL_WINDOWS = (MAIN_WINDOW, STADIUM_PANE)
