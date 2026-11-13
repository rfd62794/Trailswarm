"""One place for display scaling: DPI awareness, the effective UI scale, and scaled sizes (pure helpers + Windows reads)."""
from __future__ import annotations

import ctypes
import logging
import os
import sys

BASE_DPI = 96.0
MIN_SCALE, MAX_SCALE = 0.75, 4.0
SIDE_FRAC, SIDE_MIN, SIDE_MAX = 0.22, 260, 420   # world side panel: share of the window, clamped (px at 1x)
ENV = "POKEAGENT_UI_SCALE"
_scale = 1.0
_font_installed = False
REF_W, REF_H = 1280, 800        # the window size at which text is at its design size
MIN_WIN_SCALE, MAX_WIN_SCALE = 0.85, 1.6
FONT = "C:/Windows/Fonts/segoeui.ttf"
log = logging.getLogger(__name__)


def scale_from_dpi(dpi: float) -> float:
    return clamp(dpi / BASE_DPI)


def clamp(s: float) -> float:
    return max(MIN_SCALE, min(MAX_SCALE, s))


def env_override(environ=None) -> float | None:
    """POKEAGENT_UI_SCALE (e.g. 1.5), or None when unset/invalid."""
    raw = (os.environ if environ is None else environ).get(ENV, "").strip()
    try:
        v = float(raw)
    except ValueError:
        return None
    return clamp(v) if v > 0 else None


def effective_scale(dpi: float | None, environ=None) -> float:
    """The override wins; else the system DPI; else 1.0."""
    o = env_override(environ)
    if o is not None:
        return o
    return scale_from_dpi(dpi) if dpi else 1.0


def set_scale(s: float) -> None:
    global _scale
    _scale = clamp(s)


def get_scale() -> float:
    return _scale


def px(n: float, scale: float | None = None) -> int:
    """A fixed size in 1x pixels, scaled (use for widths/heights/margins)."""
    return int(round(n * (_scale if scale is None else scale)))


def side_panel_width(total_w: int, scale: float | None = None) -> int:
    s = _scale if scale is None else scale
    return int(max(SIDE_MIN * s, min(SIDE_MAX * s, total_w * SIDE_FRAC)))


def window_scale(w: float, h: float) -> float:
    """Text scale from the window size (1.0 at 1280x800): follows the smaller of width/height ratios, clamped."""
    return max(MIN_WIN_SCALE, min(MAX_WIN_SCALE, min(w / REF_W, h / REF_H) ** 0.5 if min(w, h) > 0 else 1.0))


def apply_window_scale(dpg, w: float, h: float) -> float:
    """Scale the global font with the window. With a crisp scaled font installed only the window factor applies (the DPI factor is
    already in the font); otherwise DPI x window."""
    f = window_scale(w, h)
    dpg.set_global_font_scale(f if _font_installed else _scale * f)
    return f


def sprite_px(zoom: float, base: float, minimum: float, scale: float | None = None) -> float:
    """On-screen sprite size: grows with zoom but never below the (scaled) minimum."""
    return max(base * zoom, minimum * (_scale if scale is None else scale))


# -- Windows reads (best effort) -------------------------------------------------------
def enable_dpi_awareness() -> bool:
    """Per-monitor DPI awareness; must run before the first window exists. Returns True when set."""
    if sys.platform != "win32":
        return False
    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, -2147024891)  # S_OK / already set
    except Exception:
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except Exception:
            return False


def system_dpi() -> float | None:
    if sys.platform != "win32":
        return None
    try:
        return float(ctypes.windll.user32.GetDpiForSystem()) or None
    except Exception:
        pass
    try:
        pct = ctypes.c_int()
        if ctypes.windll.shcore.GetScaleFactorForDevice(0, ctypes.byref(pct)) == 0 and pct.value:
            return BASE_DPI * pct.value / 100.0
        return None
    except Exception:
        return None


def init() -> float:
    """Enable DPI awareness, compute and store the scale. Call before create_context."""
    enable_dpi_awareness()
    set_scale(effective_scale(system_dpi()))
    return _scale


def install_font(dpg, scale: float | None = None, size: int = 14) -> None:
    """A crisp scaled font (Segoe UI at size*scale, any scale but 1.0); falls back to the dpg global font scale."""
    global _font_installed
    s = _scale if scale is None else scale
    if abs(s - 1.0) < 0.01:
        return
    if not os.path.exists(FONT):
        log.warning("font %s not found; using global font scale %.2f", FONT, s)
        dpg.set_global_font_scale(s)
        return
    try:
        with dpg.font_registry():
            font = dpg.add_font(FONT, int(round(size * s)))
        dpg.bind_font(font)
        _font_installed = True
    except Exception as exc:
        log.warning("font load failed (%s); using global font scale %.2f", exc, s)
        dpg.set_global_font_scale(s)
