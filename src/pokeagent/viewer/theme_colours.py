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


def rgba(hex_colour: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def text_rgba(mode: str, key: str = "text") -> tuple[int, int, int, int]:
    """A text colour of the active mode's palette (``text`` = body, ``dim`` = secondary), readable on that mode's pane."""
    return rgba(palette(mode)[key])


def state_rgb(state: str, ok: bool, mode: str = "dark") -> tuple[int, int, int, int]:
    from pokeagent.viewer.health import RING_COLOUR
    return text_rgba(mode) if ok else (*RING_COLOUR.get(state, text_rgba(mode)[:3]), 255)
