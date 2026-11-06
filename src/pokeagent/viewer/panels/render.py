"""Frame pixels -> what a UI texture needs: RGBA floats (Dear PyGui) or PNG bytes (web)."""
from __future__ import annotations

import io

from PIL import Image


def frame_rgba(rgb: bytes, w: int, h: int, out_w: int, out_h: int) -> list[float]:
    """RGB bytes -> flat RGBA float list [0..1] at ``out_w`` x ``out_h``, nearest-neighbour."""
    out: list[float] = []
    ap = out.append
    for oy in range(out_h):
        sy = oy * h // out_h
        row = rgb[sy * w * 3:(sy + 1) * w * 3]
        for ox in range(out_w):
            sx = ox * w // out_w
            i = sx * 3
            ap(row[i] / 255.0)
            ap(row[i + 1] / 255.0)
            ap(row[i + 2] / 255.0)
            ap(1.0)
    return out


def frame_png(rgb: bytes, w: int, h: int, scale: int = 2) -> bytes:
    """RGB bytes -> PNG bytes, nearest-neighbour upscaled ``scale``x (web route)."""
    im = Image.frombytes("RGB", (w, h), rgb)
    if scale != 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
