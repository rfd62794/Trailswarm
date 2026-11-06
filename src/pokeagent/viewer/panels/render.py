"""Frame pixels -> what a UI texture needs: RGBA floats (Dear PyGui) or PNG bytes (web)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image


def frame_rgba(rgb: bytes, w: int, h: int, out_w: int, out_h: int) -> np.ndarray:
    """RGB bytes -> flat RGBA float32 array [0..1] at ``out_w`` x ``out_h``, nearest-neighbour."""
    if out_w <= 0 or out_h <= 0:
        return np.zeros(0, dtype=np.float32)
    src = np.frombuffer(rgb, dtype=np.uint8, count=w * h * 3).reshape(h, w, 3)
    ys = np.arange(out_h) * h // out_h
    xs = np.arange(out_w) * w // out_w
    out = np.ones((out_h, out_w, 4), dtype=np.float32)
    out[..., :3] = src[ys][:, xs] / np.float32(255.0)
    return out.reshape(-1)


def frame_png(rgb: bytes, w: int, h: int, scale: int = 2) -> bytes:
    """RGB bytes -> PNG bytes, nearest-neighbour upscaled ``scale``x (web route)."""
    im = Image.frombytes("RGB", (w, h), rgb)
    if scale != 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
