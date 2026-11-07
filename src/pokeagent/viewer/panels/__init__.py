"""Card panels as pure view functions: snapshot in, styled lines/pixels out. No UI toolkit imports."""
from __future__ import annotations

Span = tuple[str, str]  # (text, "#rrggbb")
Line = list[Span]  # one display line = coloured segments

# Driver colours (spec 4.2) and the dark theme.
DRIVER_COLORS = {"explorer": "#5fa85f", "rl": "#c88a3a", "human": "#c0507f", "claude": "#5a8fd6"}
BG = "#1e1f24"
PANE = "#141518"
TEXT = "#d8d8d8"
DIM = "#8a8f98"
WARN = "#e0b050"
BAD = "#d06060"


def span(text: str, color: str = TEXT) -> Span:
    return (text, color)


def plain(text: str, color: str = TEXT) -> Line:
    """A single-colour line; ``""`` still yields one (empty) span so callers can index [0]."""
    return [(text, color)]


def driver_color(driver: str) -> str:
    return DRIVER_COLORS.get(driver, DIM)
