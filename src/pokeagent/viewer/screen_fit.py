"""Fit the viewer to the screen it opens on, so the control bar is never below the visible area.

Robert's laptop reports a 1536x864 work area (1920x1080 at 125% scaling); a fixed 1500x950 viewport put the
control bar off-screen. Pure sizing logic here; the Windows work-area read is best-effort (falls back to defaults).
"""
from __future__ import annotations

import ctypes
import sys

DEFAULT_W, DEFAULT_H = 1500, 950
MARGIN_W, MARGIN_H = 24, 48  # room for the OS title bar and borders


def work_area() -> tuple[int, int] | None:
    """Usable desktop size (excluding the taskbar) on Windows, else None."""
    if sys.platform != "win32":
        return None
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        if not ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
            return None
        return r.right - r.left, r.bottom - r.top
    except Exception:
        return None


def viewport_size(area: tuple[int, int] | None, scale: float = 1.0) -> tuple[int, int]:
    """Largest size up to the (scaled) defaults that fits inside the work area; both in physical pixels."""
    dw, dh = round(DEFAULT_W * scale), round(DEFAULT_H * scale)
    if not area:
        return dw, dh
    w, h = area
    return (max(640, min(dw, w - round(MARGIN_W * scale))), max(480, min(dh, h - round(MARGIN_H * scale))))


def open_viewport(clear_color) -> None:
    """DPI awareness first, then context + viewport sized in physical pixels (never taller than the screen)."""
    import dearpygui.dearpygui as dpg
    from pokeagent.viewer import ui_scale
    scale = ui_scale.init()
    dpg.create_context()
    vw, vh = viewport_size(work_area(), scale)
    dpg.create_viewport(title="PokeAgent viewer", width=vw, height=vh, x_pos=0, y_pos=0, clear_color=clear_color)
