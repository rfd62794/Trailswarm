"""Card header tint: the health colour wins when not ok, else the selection tint."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.health import OK
from pokeagent.viewer.ui import theme


def apply_header_tint(card) -> None:
    """Set the tint on ``card``'s header image (``card._img['header']``) from its health/selection state."""
    tag = card._img.get("header")
    if tag is None or not dpg.does_item_exist(tag):
        return
    state = getattr(card, "_health_state", OK)
    if state != OK and state in theme.HEADER_COLOUR:
        tint = theme.HEADER_COLOUR[state]
    else:
        tint = (120, 220, 255, 255) if getattr(card, "_sel", None) else theme.HEADER_COLOUR[OK]
    dpg.configure_item(tag, tint_color=tint)
