"""Panel colour modes (pure): dark/light palettes for the viewer chrome, and the colour of a health state's text."""
from __future__ import annotations

DARK = {"bg": "#1e1f24", "pane": "#141518", "text": "#d8d8d8", "button": "#2a2d34", "button_hover": "#3a3f4a",
        "button_active": "#4a5160", "frame": "#141518", "frame_hover": "#23262d", "dim": "#8a8f98"}
LIGHT = {"bg": "#e9ecdf", "pane": "#f6f8ee", "text": "#1d2a14", "button": "#c9d3b0", "button_hover": "#b8c598",
         "button_active": "#a2b27c", "frame": "#ffffff", "frame_hover": "#e2e8d0", "dim": "#5a6650"}
MODES = {"dark": DARK, "light": LIGHT}


def palette(mode: str) -> dict[str, str]:
    return MODES.get(mode, DARK)


def toggle(mode: str) -> str:
    return "light" if mode == "dark" else "dark"


def state_rgb(state: str, ok: bool) -> tuple[int, int, int, int]:
    from pokeagent.viewer.health import RING_COLOUR
    return (216, 216, 216, 255) if ok else (*RING_COLOUR.get(state, (216, 216, 216)), 255)
